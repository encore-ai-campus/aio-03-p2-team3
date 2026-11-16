"""Bearer HTTP 경계와 실제 어댑터 조립. 업무는 operations, SQL은 repository에 둔다."""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.auth.supabase import bearer_user_id
from app.files.validation import safe_disposition
from app.knowledge import operations
from app.knowledge.embeddings import OpenAIEmbedder
from app.knowledge.extract import OpenAIDocumentExtractor
from app.knowledge.render import PageRenderer
from app.knowledge.schemas import AttemptRequest, KnowledgeError, MAX_FILE_BYTES, ReviewRequest
from app.llm.client import DEFAULT_MODEL, OpenAIKeyError
from app.services.auth import make_cipher
from app.services.openai_keys import UserKeyAccess

def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(prefix="/api/knowledge/documents", tags=["knowledge"], dependencies=[Depends(private_response)])


def make_adapters(database, settings, owner, snapshot):
    access = UserKeyAccess(database, owner, make_cipher(settings), settings)

    def read_key():
        try:
            return access.read()
        except OpenAIKeyError as error:
            raise KnowledgeError(error.code, error.message, error.status_code) from None

    read_key()  # 접수 전과 worker 실행 전에 같은 설정 경계를 확인한다. API 호출은 하지 않는다.
    vision = snapshot.get("extraction", {}).get("model") or settings.knowledge_vision_model.strip() or settings.openai_model.strip() or DEFAULT_MODEL
    embedding = snapshot.get("embedding", {})
    model = embedding.get("model") or settings.knowledge_embedding_model.strip() or "text-embedding-3-small"
    try:
        dimensions = int(embedding.get("dimensions") or settings.knowledge_embedding_dimensions.strip() or "1536")
    except ValueError:
        raise KnowledgeError("invalid_dimensions", "임베딩 차원 설정을 확인해 주세요.", 503) from None
    if snapshot and (snapshot.get("extraction", {}).get("provider") != "openai" or embedding.get("provider") != "openai"):
        raise KnowledgeError("provider_not_configured", "저장된 처리 프로필의 공급자가 설치되지 않았습니다.", 503)
    return (PageRenderer(settings.knowledge_office_command.strip()), OpenAIDocumentExtractor(read_key, vision),
            OpenAIEmbedder(read_key, model, dimensions))


def repository(request: Request):
    return request.app.state.knowledge_repository


def storage(request: Request):
    value = request.app.state.storage
    if value is None:
        raise KnowledgeError("storage_not_configured", "비공개 파일 저장소 설정을 확인해 주세요.", 503)
    return value


@router.post("", status_code=202)
async def upload(request: Request, owner: int = Depends(bearer_user_id)):
    target_storage = storage(request)
    await run_in_threadpool(request.app.state.knowledge_adapters, owner, {})
    form = await request.form(max_files=1, max_fields=0)
    files = [value for _, value in form.multi_items() if isinstance(value, UploadFile)]
    if len(files) != 1:
        await form.close()
        raise KnowledgeError("one_file_per_request", "파일은 한 개씩 업로드해 주세요.")
    file = files[0]
    chunks, total = [], 0
    try:
        while chunk := await file.read(64 * 1024):
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                raise KnowledgeError("file_too_large", "파일은 20MiB 이하여야 합니다.", 413)
            chunks.append(chunk)
    finally:
        await form.close()
    return await run_in_threadpool(operations.upload, repository(request), target_storage, owner,
                                   file.filename or "", b"".join(chunks))


@router.get("")
def documents(request: Request, offset: int = Query(0, ge=0, le=100000), owner: int = Depends(bearer_user_id)):
    return operations.list_documents(repository(request), owner, offset)


@router.get("/{document_id}")
def detail(document_id: str, request: Request, owner: int = Depends(bearer_user_id)):
    return operations.detail(repository(request), owner, document_id)


@router.get("/{document_id}/chunks")
def chunks(document_id: str, request: Request, offset: int = Query(0, ge=0, le=100000),
           owner: int = Depends(bearer_user_id)):
    return operations.chunks(repository(request), owner, document_id, offset)


@router.get("/{document_id}/download")
def download(document_id: str, request: Request, owner: int = Depends(bearer_user_id)):
    file = operations.original(repository(request), storage(request), owner, document_id)
    return Response(file["content"], media_type=file["content_type"], headers={
        "Content-Disposition": safe_disposition(file["filename"]), "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


@router.get("/{document_id}/pages/{number}")
def preview(document_id: str, number: int, request: Request, owner: int = Depends(bearer_user_id)):
    if not 1 <= number <= 50:
        raise KnowledgeError("page_not_found", "해당 페이지가 없습니다.", 404)
    file = operations.original(repository(request), storage(request), owner, document_id)
    # ponytail: 페이지 미리보기는 원본에서 다시 렌더링한다. 조회량이 커지면 참조 관리되는 캐시를 추가한다.
    rendered = PageRenderer(request.app.state.settings.knowledge_office_command).render(
        file["content"], file["filename"], number)
    page = rendered.pages[0]
    return Response(page.png, media_type="image/png", headers={"Cache-Control": "private, no-store",
                                                              "X-Content-Type-Options": "nosniff",
                                                              "X-Page-Count": str(rendered.page_count)})


@router.post("/{document_id}/retry", status_code=202)
def retry(document_id: str, body: AttemptRequest, request: Request, owner: int = Depends(bearer_user_id)):
    operations.detail(repository(request), owner, document_id)
    request.app.state.knowledge_adapters(owner, {})
    return operations.retry(repository(request), owner, document_id, body.attempt_id)


@router.put("/{document_id}/extraction")
def review(document_id: str, body: ReviewRequest, request: Request, owner: int = Depends(bearer_user_id)):
    return operations.review(repository(request), owner, document_id, body)
