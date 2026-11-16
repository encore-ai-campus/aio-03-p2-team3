"""실제 pgvector PostgreSQL·합성 파일·가짜 외부 공급자로 수집 경계를 검증한다."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
import time
from types import SimpleNamespace
from uuid import uuid4
import zipfile

from fastapi.testclient import TestClient
from fpdf import FPDF
from PIL import Image
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from app.auth.supabase import TokenVerifier
from app.config import Settings
from app.db.engine import Database
from app.db.models import FileAsset, User, utcnow
from app.files.service import FileError, delete_file
from app.knowledge.chunking import build_chunks
from app.knowledge.embeddings import OpenAIEmbedder
from app.knowledge.extract import OpenAIDocumentExtractor, VisionPage
from app.knowledge.operations import original, process_claimed, upload
from app.knowledge.render import PageRenderer
from app.knowledge.repository import KnowledgeChild, KnowledgeDocument, KnowledgeParent, SqlRepository
from app.knowledge.router import make_adapters
from app.knowledge.schemas import EmbeddingBatch, ExtractionResult, KnowledgeError, ModelProfile, PageImage, PageText, RenderedDocument, ReviewRequest
from app.main import create_app
from tests.fakes.storage import FakeStorage
from tests.test_supabase_auth import FakeJwks, SUPABASE_URL

TEXT = "제1조 가상 조건\n납기는 확인 후 정한다. 단, 검수가 끝나야 한다.\n\n제2조 가상 대금\n검수 후 지급한다."


def png():
    buffer = BytesIO()
    Image.new("RGB", (120, 80), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def pdf(pages=2):
    document = FPDF()
    for number in range(pages):
        document.add_page()
        document.set_font("Helvetica", size=12)
        document.cell(text=f"Synthetic page {number + 1}")
    return bytes(document.output())


class FakeRenderer:
    def __init__(self, pages=1):
        self.pages = pages

    def render(self, *_args):
        return RenderedDocument([PageImage(i + 1, f"원본 페이지 {i + 1}", png()) for i in range(self.pages)], [])


class FakeExtractor:
    def __init__(self, provider="fake-vision-a", *, uncertain=False, missing=False, content=TEXT):
        self.profile = ModelProfile(provider=provider, model="vision-test", revision="v1")
        self.uncertain, self.missing, self.content = uncertain, missing, content
        self.calls = []

    def extract(self, pages):
        self.calls.append(pages)
        chosen = pages[:1] if self.missing else pages
        return ExtractionResult(profile=self.profile, pages=[PageText(number=p.number, text=self.content,
            uncertain=["가상 판독 불가 구간"] if self.uncertain else []) for p in chosen])


class FakeEmbedder:
    def __init__(self, dimensions=3, provider="fake-embedding-a", *, fail_after=None, invalid=None):
        self.profile = ModelProfile(provider=provider, model="embedding-test", revision="v1", dimensions=dimensions)
        self.calls, self.fail_after, self.invalid = [], fail_after, invalid

    def embed_documents(self, texts):
        self.calls.append(texts)
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise KnowledgeError("provider_unavailable", "가상 공급자 실패")
        vectors = [[0.25] * self.profile.dimensions for _ in texts]
        if self.invalid == "nan": vectors[0][0] = float("nan")
        if self.invalid == "inf": vectors[0][0] = float("inf")
        if self.invalid == "dimension": vectors[0].append(0)
        if self.invalid == "count": vectors.pop()
        return EmbeddingBatch(profile=self.profile, vectors=vectors)


def setup_document(database, *, data=None, name="가상.png"):
    repository, storage = SqlRepository(database), FakeStorage()
    document = upload(repository, storage, 1, name, data or png())
    return repository, storage, document


def run(repository, storage, extractor=None, embedder=None, renderer=None):
    job = repository.claim()
    assert job is not None
    return process_claimed(repository, storage, renderer or FakeRenderer(),
                           extractor or FakeExtractor(), embedder or FakeEmbedder(), job)


def test_pipeline_uses_real_pgvector_parent_ranges_and_model_swap(database):
    repository, storage, document = setup_document(database, data=pdf(), name="가상.pdf")
    extractor, embedder = FakeExtractor(), FakeEmbedder()
    assert run(repository, storage, extractor, embedder, PageRenderer()) == "ready"
    assert len(extractor.calls[0]) == 2 and all(p.png.startswith(b"\x89PNG") for p in extractor.calls[0])
    detail = repository.read(1, document["id"])
    chunks = repository.chunks(1, document["id"])
    assert detail["parent_count"] >= 2 and detail["child_count"] > 0
    parents = {p["id"]: p for p in chunks["parents"]}
    for child in chunks["children"]:
        parent = parents[child["parent_id"]]
        assert child["text"] == parent["text"][child["start"]:child["end"]]
        assert parent["sources"] and child["dimensions"] == 3
    with database.session() as session:
        assert session.scalar(text("SELECT vector_dims(embedding) FROM knowledge_chunks LIMIT 1")) == 3
        assert session.scalar(text("SELECT count(*) FROM pg_class WHERE relname LIKE 'knowledge_%' AND relrowsecurity")) == 3
    repository.retry(1, document["id"], detail["attempt_id"])
    second = FakeEmbedder(5, "fake-embedding-b")
    assert run(repository, storage, FakeExtractor("fake-vision-b"), second) == "ready"
    detail = repository.read(1, document["id"])
    assert detail["published_profile"]["embedding"]["dimensions"] == 5
    assert detail["published_profile"]["extraction"]["provider"] == "fake-vision-b"
    assert {c["dimensions"] for c in repository.chunks(1, document["id"])["children"]} == {5}


def test_missing_page_waits_for_complete_review_and_revision_fencing(database):
    repository, storage, document = setup_document(database)
    extractor, embedder = FakeExtractor(missing=True), FakeEmbedder()
    assert run(repository, storage, extractor, embedder, FakeRenderer(2)) == "needs_review"
    detail = repository.read(1, document["id"])
    assert not embedder.calls and len(detail["pages"]) == 2 and not detail["pages"][1]["complete"]
    body = {"attempt_id": detail["attempt_id"], "revision": detail["revision"],
            "pages": [{"number": 1, "text": TEXT}, {"number": 2, "text": "누락된 가상 조항을 확인했다."}]}
    with pytest.raises(KnowledgeError, match="페이지"):
        repository.review(1, document["id"], ReviewRequest(**{**body, "pages": body["pages"][:1]}))
    repository.review(1, document["id"], ReviewRequest(**body))
    with pytest.raises(KnowledgeError) as conflict:
        repository.review(1, document["id"], ReviewRequest(**body, confirm=True))
    assert conflict.value.status == 409
    updated = repository.read(1, document["id"])
    repository.review(1, document["id"], ReviewRequest(**{**body, "revision": updated["revision"]}, confirm=True))
    assert run(repository, storage, extractor, embedder) == "ready"
    assert len(extractor.calls) == 1 and len(embedder.calls) == 1
    assert repository.read(1, document["id"])["published_pages"][1]["text"] == body["pages"][1]["text"]


@pytest.mark.parametrize("invalid", ["nan", "inf", "dimension", "count"])
def test_invalid_vectors_never_publish(database, invalid):
    repository, storage, document = setup_document(database)
    assert run(repository, storage, embedder=FakeEmbedder(invalid=invalid)) == "failed"
    detail = repository.read(1, document["id"])
    assert detail["published_attempt_id"] is None and detail["child_count"] == 0
    assert detail["error_code"] == "embedding_mismatch"


def test_partial_batch_failure_preserves_successful_index(database):
    repository, storage, document = setup_document(database)
    assert run(repository, storage) == "ready"
    previous = repository.chunks(1, document["id"])
    detail = repository.read(1, document["id"])
    repository.retry(1, document["id"], detail["attempt_id"])
    long_text = "제1조 가상 장문\n" + ("가상 문장과 검수 조건을 보존한다.\n" * 2000)
    assert run(repository, storage, FakeExtractor(content=long_text), FakeEmbedder(fail_after=1)) == "failed"
    assert repository.chunks(1, document["id"]) == previous
    assert repository.read(1, document["id"])["published_attempt_id"] == detail["published_attempt_id"]


def test_expired_claim_cannot_overwrite_or_automatically_requeue(database):
    repository, storage, document = setup_document(database)
    job = repository.claim()
    with database.session() as session:
        session.execute(update(KnowledgeDocument).where(KnowledgeDocument.id == document["id"])
                        .values(lease_until=utcnow() - timedelta(seconds=1)))
    repository.expire()
    assert repository.claim() is None
    expired = repository.read(1, document["id"])
    assert expired["status"] == "failed" and expired["error_code"] == "processing_interrupted"
    new = repository.retry(1, document["id"], job["attempt_id"])
    assert new["attempt_id"] != job["attempt_id"]
    assert not repository.update_attempt(document["id"], job["attempt_id"], status="ready")
    assert process_claimed(repository, storage, FakeRenderer(), FakeExtractor(), FakeEmbedder(), job) == "stale"
    assert run(repository, storage) == "ready"


def test_duplicate_is_atomic_per_owner_and_file_reference_is_protected(database):
    repository, storage = SqlRepository(database), FakeStorage()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: upload(repository, storage, 1, "same.png", png()), range(2)))
    assert results[0]["id"] == results[1]["id"]
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(KnowledgeDocument)) == 1
        assert session.scalar(select(func.count()).select_from(FileAsset)) == 1
        session.add(User(id=2, google_sub="other-fake", email="other@example.invalid"))
    other = upload(repository, storage, 2, "same.png", png())
    assert other["id"] != results[0]["id"]
    with pytest.raises(KnowledgeError) as denied:
        repository.read(2, results[0]["id"])
    assert denied.value.status == 404
    with pytest.raises(FileError) as protected:
        delete_file(database, storage, 1, results[0]["file_id"])
    assert protected.value.code == "file_in_use"


def test_parent_child_foreign_key_rejects_cross_scope_and_dimensions(database):
    repository, storage, document = setup_document(database)
    assert run(repository, storage) == "ready"
    with database.session() as session:
        child = session.scalar(select(KnowledgeChild))
        values = {c.name: getattr(child, c.name) for c in KnowledgeChild.__table__.columns}
    for patch in ({"attempt_id": str(uuid4())}, {"user_id": 999}, {"dimensions": 4}):
        with pytest.raises(IntegrityError):
            with database.session() as session:
                session.add(KnowledgeChild(**{**values, "id": str(uuid4()), "ordinal": 900, **patch}))
    assert repository.read(1, document["id"])["status"] == "ready"


def test_extension_in_existing_schema_and_repeated_migration(database_url):
    db = Database(database_url)
    with db.engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA extensions")
        connection.exec_driver_sql("CREATE EXTENSION vector WITH SCHEMA extensions")
    db.create_tables()
    db.create_tables()
    with db.session() as session:
        session.add(User(id=1, google_sub="schema-test", email="schema@example.invalid"))
    repository, storage = SqlRepository(db), FakeStorage()
    # 사용자 준비 뒤 생성한 새 문서로 다른 확장 스키마에서도 실제 벡터 저장을 확인한다.
    document = upload(repository, storage, 1, "schema.png", png())
    assert run(repository, storage) == "ready"
    assert repository.read(1, document["id"])["child_count"] > 0
    db.close()


def test_provider_adapters_preserve_mapping_and_request_options():
    calls = []
    class FakeClient:
        def __init__(self, **kwargs): calls.append(kwargs)
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        @property
        def responses(self): return self
        @property
        def embeddings(self): return self
        def parse(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(status="completed", output_parsed=VisionPage(text=TEXT, blank=False, complete=True, uncertain=[]))
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(index=1, embedding=[0.2, 0.3]), SimpleNamespace(index=0, embedding=[0.4, 0.5])])
    extractor = OpenAIDocumentExtractor(lambda: "fake-key", "configured-model", client_factory=FakeClient)
    result = extractor.extract([PageImage(7, "변환 페이지 7", png())])
    assert result.pages[0].number == 7 and result.pages[0].source == "변환 페이지 7"
    request = next(c for c in calls if "instructions" in c)
    assert request["store"] is False and request["input"][0]["content"][1]["type"] == "input_image"
    embedder = OpenAIEmbedder(lambda: "fake-key", "text-embedding-3-small", 2, client_factory=FakeClient)
    assert embedder.embed_documents(["a", "b"]).vectors == [[0.4, 0.5], [0.2, 0.3]]
    assert all(c["max_retries"] == 0 for c in calls if "api_key" in c)


def test_upload_review_ready_and_owner_isolation_over_http(database_url):
    jwks, storage = FakeJwks(), FakeStorage()
    extractor, embedder = FakeExtractor(uncertain=True), FakeEmbedder()
    app = create_app(Settings(database_url=database_url, session_secret="test-only"),
                     supabase_auth=TokenVerifier(SUPABASE_URL, fetch_jwks=jwks.serve), storage=storage,
                     knowledge_adapters=lambda *_: (FakeRenderer(), extractor, embedder))
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {jwks.token()}"}
        response = client.post("/api/knowledge/documents", headers=headers, files={"file": ("fake.png", png())})
        assert response.status_code == 202, response.text
        document_id = response.json()["id"]
        path = f"/api/knowledge/documents/{document_id}"
        for _ in range(200):
            detail = client.get(path, headers=headers).json()
            if detail["status"] == "needs_review": break
            time.sleep(.02)
        assert detail["status"] == "needs_review" and not embedder.calls
        assert client.get(path + "/download", headers=headers).content == png()
        assert client.get(path + "/pages/1", headers=headers).headers["content-type"].startswith("image/png")
        result = client.put(path + "/extraction", headers=headers, json={"attempt_id": detail["attempt_id"],
            "revision": detail["revision"], "pages": [{"number": 1, "text": TEXT}], "confirm": True})
        assert result.status_code == 200, result.text
        for _ in range(200):
            detail = client.get(path, headers=headers).json()
            if detail["status"] == "ready": break
            time.sleep(.02)
        assert detail["status"] == "ready" and detail["child_count"] > 0
        assert client.get(path + "/chunks", headers=headers).json()["parents"]
        other = {"Authorization": f"Bearer {jwks.token(sub=uuid4())}"}
        for suffix in ("", "/download", "/pages/1", "/chunks"):
            assert client.get(path + suffix, headers=other).status_code == 404
        assert client.get(path).status_code == 401


def office_bytes(extension="docx", *, hidden=False, formula=False):
    from xml.sax.saxutils import escape
    namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
    content_namespace = "http://schemas.openxmlformats.org/package/2006/content-types"
    part = "word/document.xml" if extension == "docx" else "xl/workbook.xml"
    content_type = "wordprocessingml.document.main+xml" if extension == "docx" else "spreadsheetml.sheet.main+xml"
    entries = {
        "[Content_Types].xml": f'<Types xmlns="{content_namespace}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/{part}" ContentType="application/vnd.openxmlformats-officedocument.{content_type}"/>' + ('<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' if extension == "xlsx" else '') + '</Types>',
        "_rels/.rels": f'<Relationships xmlns="{namespace}"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="{part}"/></Relationships>',
    }
    if extension == "docx":
        entries[part] = f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{escape(TEXT)}</w:t></w:r></w:p></w:body></w:document>'
    else:
        entries[part] = '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="가상 표" sheetId="1" r:id="rId1" state="' + ('hidden' if hidden else 'visible') + '"/></sheets></workbook>'
        entries["xl/_rels/workbook.xml.rels"] = f'<Relationships xmlns="{namespace}"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
        entries["xl/worksheets/sheet1.xml"] = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>가상 한글 표 / Synthetic table</t></is></c><c r="B1">' + ('<f>1+1</f>' if formula else '<v>2</v>') + '</c></row></sheetData></worksheet>'
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items(): archive.writestr(name, content)
    return buffer.getvalue()


@pytest.mark.parametrize("name,data", [("sample.docx", office_bytes()), ("sample.xlsx", office_bytes("xlsx")),
                                      ("sample.txt", "가상 한글 문서\nSynthetic test".encode()), ("image.png", png())])
def test_real_page_rendering_for_supported_formats(name, data):
    result = PageRenderer().render(data, name)
    assert result.pages and result.pages[0].png.startswith(b"\x89PNG")
    if name.endswith(("docx", "xlsx", "txt")):
        assert "converted_layout_requires_review" in result.warnings
        assert result.pages[0].source == "변환 페이지 1"


@pytest.mark.parametrize("data,code", [(office_bytes("xlsx", hidden=True), "hidden_sheet"),
                                     (office_bytes("xlsx", formula=True), "formula_cache_missing")])
def test_office_content_that_cannot_be_rendered_is_not_silently_accepted(data, code):
    with pytest.raises(KnowledgeError) as failure:
        PageRenderer().render(data, "sample.xlsx")
    assert failure.value.code == code


def test_render_page_limit_encrypted_or_broken_pdf_and_timeout():
    with pytest.raises(KnowledgeError) as failure:
        PageRenderer().render(pdf(51), "large.pdf")
    assert failure.value.code == "page_limit"
    with pytest.raises(KnowledgeError):
        PageRenderer().render(b"%PDF-1.4\ninvalid", "broken.pdf")
    with pytest.raises(KnowledgeError) as timeout:
        PageRenderer(timeout=.001).render(pdf(1), "timeout.pdf")
    assert timeout.value.code == "render_timeout"


def test_missing_key_and_pc_mode_cannot_fall_back_to_server_key(database):
    settings = Settings(openai_api_key="not-a-permitted-server-fallback")
    _, extractor, _ = make_adapters(database, settings, 1, {})
    with pytest.raises(KnowledgeError) as missing:
        extractor.read_key()
    assert missing.value.code == "OPENAI_KEY_REQUIRED"
    with database.session() as session:
        session.get(User, 1).ai_execution_mode = "local_worker"
    with pytest.raises(KnowledgeError) as forbidden:
        extractor.read_key()
    assert forbidden.value.code == "LOCAL_WORKER_KEY_FORBIDDEN"


def test_sql_failure_during_replacement_rolls_back_old_index_without_exposing_text(database):
    repository, storage, document = setup_document(database)
    assert run(repository, storage) == "ready"
    previous = repository.chunks(1, document["id"])
    detail = repository.read(1, document["id"])
    updated = repository.review(1, document["id"], ReviewRequest(
        attempt_id=detail["attempt_id"], revision=detail["revision"], confirm=True,
        pages=[{"number": 1, "text": "가상 새 원문: SQL 오류에 노출되면 안 된다."}]))
    job = repository.claim()
    assert repository.update_attempt(document["id"], job["attempt_id"], status="embedding")
    parents, children = build_chunks([PageText(number=1, text="가상 새 원문: SQL 오류에 노출되면 안 된다.")])
    with pytest.raises(KnowledgeError) as failure:
        repository.publish(document["id"], updated["attempt_id"], parents, children,
                           [[0.1, 0.2]] * len(children), FakeEmbedder(3).profile)
    assert failure.value.code == "knowledge_database_unavailable"
    assert "가상 새 원문" not in str(failure.value)
    assert repository.chunks(1, document["id"]) == previous
    assert repository.read(1, document["id"])["published_attempt_id"] == detail["published_attempt_id"]


@pytest.mark.parametrize("name,data,code", [("wrong.txt", b"%PDF-1.4\nFake", "signature_mismatch"),
                                          ("unknown.hwp", b"fake", "unsupported_format"),
                                          ("empty.txt", b"", "empty_file"),
                                          ("large.txt", b"x" * (20 * 1024 * 1024 + 1), "file_too_large")])
def test_invalid_uploads_do_not_create_storage_or_document(database, name, data, code):
    storage, repository = FakeStorage(), SqlRepository(database)
    with pytest.raises(KnowledgeError) as failure:
        upload(repository, storage, 1, name, data)
    assert failure.value.code == code
    assert not storage.calls and not repository.list(1)
