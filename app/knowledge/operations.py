"""문서 수집 업무. SQLAlchemy·FastAPI·비전/임베딩 SDK를 import하지 않는다."""
from hashlib import sha256
from uuid import uuid4

from app.knowledge.chunking import build_chunks
from app.knowledge.ports import DocumentExtractor, Embedder, Renderer, Repository, Storage
from app.knowledge.schemas import CHUNK_VERSION, KnowledgeError, MAX_TEXT_CHARS, PageText, ReviewRequest
from app.knowledge.validation import validate_upload


def upload(repository: Repository, storage: Storage, owner: int, filename: str, data: bytes) -> dict:
    filename, content_type = validate_upload(filename, data)
    digest = sha256(data).hexdigest()
    existing = repository.duplicate(owner, digest)
    if existing:
        return {**existing, "duplicate": True}
    key = f"{owner}/attachments/{uuid4().hex}"
    try:
        storage.upload(key, data, content_type)
    except Exception:
        raise KnowledgeError("storage_unavailable", "원본을 저장하지 못했습니다. 저장소 상태를 확인해 주세요.", 503) from None
    result = repository.create(owner, {"original_filename": filename, "content_type": content_type,
                                       "size_bytes": len(data), "sha256": digest, "object_key": key})
    return {"duplicate": False, **result}


def list_documents(repository: Repository, owner: int, offset: int) -> dict:
    return {"documents": repository.list(owner, offset=offset)}


def detail(repository: Repository, owner: int, document_id: str) -> dict:
    return repository.read(owner, document_id)


def chunks(repository: Repository, owner: int, document_id: str, offset: int) -> dict:
    return repository.chunks(owner, document_id, offset)


def retry(repository: Repository, owner: int, document_id: str, attempt_id: str) -> dict:
    return repository.retry(owner, document_id, attempt_id)


def review(repository: Repository, owner: int, document_id: str, request: ReviewRequest) -> dict:
    return repository.review(owner, document_id, request)


def original(repository: Repository, storage: Storage, owner: int, document_id: str) -> dict:
    metadata = repository.original(owner, document_id)
    try:
        content = storage.download(metadata["object_key"])
    except Exception:
        raise KnowledgeError("storage_unavailable", "원본을 읽지 못했습니다. 저장소 상태를 확인해 주세요.", 503) from None
    if sha256(content).hexdigest() != metadata["sha256"]:
        raise KnowledgeError("object_corrupted", "저장된 원본이 업로드 기록과 일치하지 않습니다.", 503)
    return {**metadata, "content": content}


def _reconcile(result, images, warnings):
    by_number = {p.number: p for p in result.pages}
    if [p.number for p in result.pages] != [p.number for p in images]:
        warnings.append("page_mapping_requires_review")
    pages = []
    for image in images:
        page = by_number.get(image.number)
        if page is None:
            page = PageText(number=image.number, text="", complete=False, uncertain=["전사 결과에서 페이지 누락"])
        page = page.model_copy(update={"source": image.source})
        pages.append(page)
        if (not page.complete or page.uncertain or "[판독 불가]" in page.text
                or bool(page.text.strip()) == page.blank):
            warnings.append("transcription_requires_review")
    if sum(len(p.text) for p in pages) > MAX_TEXT_CHARS:
        raise KnowledgeError("text_limit", "추출문이 100만 자를 넘습니다. 문서를 나누어 주세요.")
    if not any(p.text.strip() for p in pages):
        warnings.append("empty_transcription_requires_review")
    return pages, list(dict.fromkeys(warnings))


def process_claimed(repository: Repository, storage: Storage, renderer: Renderer,
                    extractor: DocumentExtractor, embedder: Embedder, job: dict) -> str:
    document_id, attempt_id = job["id"], job["attempt_id"]
    stage = "extracting"
    try:
        profile = {"extraction": extractor.profile.model_dump(), "embedding": embedder.profile.model_dump(),
                   "rendering": "pdfium-pages-v1", "chunking": CHUNK_VERSION}
        if job["profile"] and job["profile"] != profile:
            raise KnowledgeError("profile_mismatch", "처리 시도에 고정한 모델 프로필이 달라졌습니다.")
        if not repository.update_attempt(document_id, attempt_id, profile=profile):
            return "stale"
        if job["approved"]:
            pages = [PageText.model_validate(p) for p in job["pages"]]
        else:
            file = original(repository, storage, job["user_id"], document_id)
            rendered = renderer.render(file["content"], file["filename"])
            result = extractor.extract(rendered.pages)
            if result.profile != extractor.profile:
                raise KnowledgeError("profile_mismatch", "비전 응답의 모델 프로필이 다릅니다.")
            pages, warnings = _reconcile(result, rendered.pages, [*rendered.warnings, *result.warnings])
            values = [p.model_dump() for p in pages]
            status = "needs_review" if warnings else "chunking"
            if not repository.update_attempt(document_id, attempt_id, raw_pages=values, pages=values,
                                             approved=not warnings, warnings=warnings, status=status):
                return "stale"
            if warnings:
                return "needs_review"
        stage = "chunking"
        if not repository.update_attempt(document_id, attempt_id, status=stage):
            return "stale"
        parents, children = build_chunks(pages)
        stage = "embedding"
        if not repository.update_attempt(document_id, attempt_id, status=stage):
            return "stale"
        vectors = []
        for offset in range(0, len(children), 32):
            # 임대/시도가 바뀌었다면 다음 유료 배치를 보내지 않는다.
            if not repository.update_attempt(document_id, attempt_id, status=stage):
                return "stale"
            texts = [child.text for child in children[offset:offset + 32]]
            batch = embedder.embed_documents(texts)
            batch.validate_for(len(texts), embedder.profile)
            vectors.extend(batch.vectors)
        return "ready" if repository.publish(document_id, attempt_id, parents, children, vectors, embedder.profile) else "stale"
    except Exception as error:
        # 외부 응답 원문/SQL 매개변수/키를 로그나 API 오류에 복사하지 않는다.
        code = error.code if isinstance(error, KnowledgeError) else "processing_failed"
        repository.update_attempt(document_id, attempt_id, status="failed", error_code=code, error_stage=stage)
        return "failed"
