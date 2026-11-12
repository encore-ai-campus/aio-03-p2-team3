"""계획 8절: 비공개 Storage 첨부 API를 가짜 Storage·실제 PostgreSQL로 검증한다.

업로드→다운로드 해시 일치·메타데이터만 DB, 크기·빈 파일·위장 형식·여러 파일 거부, 타인 파일 404,
업로드 성공+SQL 실패(미참조 객체 잔존·재요청), 삭제(미참조만·연결 중 거부·객체 삭제 실패), 문서 출처
연결(기대 revision·개수·소유 검증, 새 revision·대기 검토 무효화·과거 연결 보존), 미참조 객체 목록·
수동 정리 명령을 본다. 실제 Supabase Storage HTTP는 부르지 않는다.
"""
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from uuid import uuid4
import zipfile

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.models import FileAsset, TradeDocumentSource, TradeProposal
from app.files import cleanup
from app.files.storage import StorageError
from app.main import create_app
from app.auth.supabase import TokenVerifier
from tests.fakes.storage import FakeStorage, storage_error
from tests.test_pi_domain import pi_input
from tests.test_supabase_auth import SUPABASE_URL, FakeJwks, write_settings
from tests.test_trade_flow import seal_png

MAX_BYTES = 5 * 1024 * 1024


def settings_of(database_url):
    return Settings(database_url=database_url, session_secret="test-session-secret")


def make_client(database_url, jwks, storage, *, settings=None, raise_server_exceptions=True):
    verifier = TokenVerifier(SUPABASE_URL, fetch_jwks=jwks.serve)
    app = create_app(settings or settings_of(database_url), supabase_auth=verifier, storage=storage)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def pdf_bytes():
    return b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"


def xlsx_bytes():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships/>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook/>')
    return buffer.getvalue()


def upload(client, headers, filename, data, content_type="application/octet-stream"):
    return client.post("/api/files", headers=headers,
                       files={"file": (filename, data, content_type)})


def uploaded(client, headers, data=None, filename="거래 문서.pdf"):
    response = upload(client, headers, filename, data or pdf_bytes())
    assert response.status_code == 200, response.text
    return response.json()


def sources_of(client, document_id):
    with client.app.state.database.session() as session:
        return list(session.scalars(select(TradeDocumentSource).where(
            TradeDocumentSource.trade_document_id == document_id).order_by(TradeDocumentSource.revision)))


def file_rows(client):
    with client.app.state.database.session() as session:
        return list(session.scalars(select(FileAsset).order_by(FileAsset.id)))


def create_pi_document(client, headers):
    write_settings(client, headers)
    assert client.post("/api/trade/settings/branding/seal", headers=headers, files={
        "image": ("seal.png", seal_png(), "image/png")}).status_code == 200
    response = client.post("/api/trade/pi", headers=headers, json=pi_input().model_dump(mode="json"))
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_download_roundtrip_keeps_bytes_in_storage_and_metadata_in_db(database_url):
    jwks, storage = FakeJwks(), FakeStorage()
    with make_client(database_url, jwks, storage) as client:
        headers = bearer(jwks.token())
        user_id = client.get("/api/me", headers=headers).json()["user_id"]
        data = pdf_bytes()

        body = uploaded(client, headers, data)
        assert body == {"file_id": body["file_id"], "filename": "거래 문서.pdf",
                        "content_type": "application/pdf", "size_bytes": len(data),
                        "sha256": sha256(data).hexdigest()}

        [row] = file_rows(client)
        assert (row.user_id, row.sha256, row.size_bytes) == (user_id, body["sha256"], len(data))
        # object key는 서버가 만들었고 원래 파일명을 쓰지 않는다.
        assert row.object_key.startswith(f"{user_id}/attachments/")
        assert "거래" not in row.object_key and ".pdf" not in row.object_key
        [object_key] = list(storage.objects)
        assert storage.objects[object_key] == data  # bytes는 Storage에만 있다

        metadata = client.get(f"/api/files/{body['file_id']}", headers=headers)
        assert metadata.status_code == 200
        assert metadata.json()["filename"] == "거래 문서.pdf"
        assert metadata.json()["created_at"]

        download = client.get(f"/api/files/{body['file_id']}/download", headers=headers)
        assert download.status_code == 200
        assert download.content == data  # 정상 업로드/다운로드 해시가 같다
        assert download.headers["cache-control"] == "no-store"
        assert download.headers["x-content-type-options"] == "nosniff"
        assert download.headers["content-type"] == "application/pdf"
        disposition = download.headers["content-disposition"]
        assert disposition.startswith("attachment; ")
        assert "거래" not in disposition and "%EA%B1%B0" in disposition  # 원본 이름은 UTF-8 인코딩으로만


def test_upload_rejects_bad_size_empty_disguised_and_multi_files(database_url):
    jwks, storage = FakeJwks(), FakeStorage()
    with make_client(database_url, jwks, storage) as client:
        headers = bearer(jwks.token())
        cases = [
            ("용량 초과", 413, "file_too_large",
             upload(client, headers, "big.txt", b"a" * (MAX_BYTES + 1), "text/plain")),
            ("빈 파일", 422, "empty_file", upload(client, headers, "empty.pdf", b"", "application/pdf")),
            ("위장 PDF(PNG bytes)", 415, "signature_mismatch",
             upload(client, headers, "fake.pdf", b"\x89PNG\r\n\x1a\nfake", "application/pdf")),
            ("PDF bytes에 txt 이름", 415, "signature_mismatch",
             upload(client, headers, "fake.txt", pdf_bytes(), "text/plain")),
            ("허용 밖 확장자", 415, "unsupported_media_type",
             upload(client, headers, "program.exe", b"MZ\x90\x00", "application/octet-stream")),
            ("내용 없는 zip", 415, "unsupported_media_type",
             upload(client, headers, "plain.zip", b"PK\x03\x04" + b"0" * 40,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
            ("바이너리 쓰레기", 415, "unsupported_media_type",
             upload(client, headers, "blob.bin", b"\x00\x01\x02\x03", "application/octet-stream")),
            ("파일 여러 개", 422, "one_file_per_request",
             client.post("/api/files", headers=headers, files={
                 "file": ("a.pdf", pdf_bytes(), "application/pdf"),
                 "more": ("b.txt", b"text", "text/plain")})),
            ("파일 없음", 422, "one_file_per_request",
             client.post("/api/files", headers=headers, data={"note": "파일 아님"})),
            ("이름 없음", 422, "filename_required", upload(client, headers, " ", b"text", "text/plain")),
        ]
        for name, status, code, response in cases:
            assert response.status_code == status, f"{name}: {response.text}"
            assert response.json()["error"]["code"] == code, name
        assert file_rows(client) == [] and storage.objects == {}  # 거부된 요청은 아무 것도 남기지 않는다

        # 허용 형식은 경계값 포함해 전부 저장된다(5MiB 딱 맞는 텍스트·XLSX·PNG).
        exact = upload(client, headers, "max.txt", b"a" * MAX_BYTES, "text/plain")
        assert exact.status_code == 200 and exact.json()["content_type"] == "text/plain; charset=utf-8"
        assert upload(client, headers, "list.xlsx", xlsx_bytes(),
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                      ).json()["content_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert upload(client, headers, "mark.png", b"\x89PNG\r\n\x1a\n", "image/png"
                      ).json()["content_type"] == "image/png"
        assert upload(client, headers, "photo.jpg", b"\xff\xd8\xff\xe0thumbnail", "image/jpeg"
                      ).json()["content_type"] == "image/jpeg"


def test_files_require_bearer_token_and_storage_configuration(database_url):
    jwks = FakeJwks()
    with make_client(database_url, jwks, None) as client:  # Storage 미설정
        token = jwks.token()
        assert client.post("/api/files", files={"file": ("a.pdf", pdf_bytes(), "application/pdf")}
                           ).status_code == 401  # 토큰 없음
        response = upload(client, bearer(token), "a.pdf", pdf_bytes())
        assert response.status_code == 503 and response.json()["error"]["code"] == "storage_not_configured"
        assert client.get("/api/files/1/download", headers=bearer(token)).json()["error"]["code"] \
            == "storage_not_configured"


def test_upload_sql_failure_leaves_unreferenced_object_and_retry_succeeds(database_url, monkeypatch):
    jwks, storage = FakeJwks(), FakeStorage()
    with make_client(database_url, jwks, storage, raise_server_exceptions=False) as client:
        headers = bearer(jwks.token())

        class ExplodingAsset:
            def __init__(self, **values):
                raise RuntimeError("SQL 실패")

        monkeypatch.setattr("app.files.service.FileAsset", ExplodingAsset)
        response = upload(client, headers, "one.pdf", pdf_bytes())
        assert response.status_code == 500  # 가짜 성공 없음: SQL 실패는 실패로 돌아간다
        assert file_rows(client) == []
        [object_key] = list(storage.objects)  # 업로드 성공+SQL 실패 → 미참조 객체로 남는다(요청 실패 처리에서 지우지 않음)
        assert storage.objects[object_key] == pdf_bytes()

        monkeypatch.setattr("app.files.service.FileAsset", FileAsset)
        body = uploaded(client, headers, pdf_bytes())  # 재요청은 새 파일로 성공한다
        [kept] = file_rows(client)
        assert kept.id == body["file_id"]
        assert set(storage.objects) == {object_key, kept.object_key}
        listed = cleanup.unreferenced_objects(client.app.state.database, storage)
        assert [row["key"] for row in listed] == [object_key]  # 정리 명령이 미참조 객체만 잡는다


def test_delete_only_unreferenced_files_and_rejects_linked_files(database_url):
    jwks, storage = FakeJwks(), FakeStorage()
    with make_client(database_url, jwks, storage) as client:
        headers = bearer(jwks.token())
        document = create_pi_document(client, headers)
        branding_row = file_rows(client)[0]  # 설정 직인 이미지(회사 설정이 참조 중, 계획 9절)
        assert client.delete(f"/api/files/{branding_row.id}", headers=headers).status_code == 409
        linked = uploaded(client, headers)
        free = uploaded(client, headers)

        response = client.put(f"/api/trade/pi/{document['document_id']}/sources", headers=headers,
                              json={"revision": document["revision"], "file_ids": [linked["file_id"]]})
        assert response.status_code == 200, response.text
        assert response.json()["revision"] == document["revision"] + 1

        in_use = client.delete(f"/api/files/{linked['file_id']}", headers=headers)  # 연결 중 삭제 거부
        assert in_use.status_code == 409 and in_use.json()["error"]["code"] == "file_in_use"

        deleted = client.delete(f"/api/files/{free['file_id']}", headers=headers)
        assert deleted.status_code == 204
        assert client.get(f"/api/files/{free['file_id']}", headers=headers).status_code == 404
        assert client.delete(f"/api/files/{free['file_id']}", headers=headers).status_code == 404  # 재요청 404
        linked_row = [row for row in file_rows(client) if row.id == linked["file_id"]][0]
        assert set(storage.objects) == {branding_row.object_key, linked_row.object_key}  # 삭제한 객체만 Storage에서 없어졌다


def test_delete_storage_failure_returns_error_and_cleanup_reclaims(database_url):
    jwks, storage = FakeJwks(), FakeStorage()
    with make_client(database_url, jwks, storage) as client:
        headers = bearer(jwks.token())
        body = uploaded(client, headers)

        storage.delete_error = storage_error()
        response = client.delete(f"/api/files/{body['file_id']}", headers=headers)
        assert response.status_code == 503  # 삭제 실패는 실패로 알린다
        assert response.json()["error"]["code"] == "storage_cleanup_failed"
        assert client.get(f"/api/files/{body['file_id']}", headers=headers).status_code == 404  # 기록은 지워졌다
        [object_key] = list(storage.objects)  # 남은 bytes는 미참조 객체 → 수동 정리 대상
        storage.age_object(object_key, hours=3)

        storage.delete_error = None
        rows, deleted = cleanup.execute(client.app.state.database, storage,
                                        older_than_hours=1, delete=True, confirmed=True)
        assert [row["key"] for row in rows] == [object_key]
        assert deleted == [object_key] and storage.objects == {}


def test_sources_link_checks_owner_revision_count_and_invalidates_review(database_url):
    jwks, storage = FakeJwks(), FakeStorage()
    with make_client(database_url, jwks, storage) as client:
        headers = bearer(jwks.token())
        document = create_pi_document(client, headers)
        document_id = document["document_id"]
        first = uploaded(client, headers)
        second = uploaded(client, headers, filename="목록.xlsx", data=xlsx_bytes())

        proposal = client.post(f"/api/trade/pi/{document_id}/reviews", headers=headers,
                               json={"revision": document["revision"]})
        assert proposal.status_code == 201, proposal.text
        proposal_id = proposal.json()["id"]

        stale = client.put(f"/api/trade/pi/{document_id}/sources", headers=headers,
                           json={"revision": document["revision"] + 5, "file_ids": [first["file_id"]]})
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "REVISION_CONFLICT"
        too_many = client.put(f"/api/trade/pi/{document_id}/sources", headers=headers,
                              json={"revision": 1, "file_ids": [1, 2, 3, 4, 5, 6]})
        assert too_many.status_code == 422  # 문서당 5개
        duplicate = client.put(f"/api/trade/pi/{document_id}/sources", headers=headers,
                               json={"revision": 1, "file_ids": [first["file_id"], first["file_id"]]})
        assert duplicate.status_code == 422 and duplicate.json()["error"]["code"] == "DUPLICATE_FILE_IDS"
        missing = client.put(f"/api/trade/pi/{document_id}/sources", headers=headers,
                             json={"revision": 1, "file_ids": [9999]})
        assert missing.status_code == 422 and missing.json()["error"]["code"] == "FILE_NOT_OWNED"
        assert client.put(f"/api/trade/po/{document_id}/sources", headers=headers,
                          json={"revision": 1, "file_ids": [first["file_id"]]}
                          ).status_code == 404  # 문서 종류가 다르면 없는 문서다

        response = client.put(f"/api/trade/pi/{document_id}/sources", headers=headers,
                              json={"revision": document["revision"], "file_ids": [first["file_id"]]})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["revision"] == 2 and [f["file_id"] for f in body["files"]] == [first["file_id"]]
        assert client.get(f"/api/trade/pi/{document_id}", headers=headers).json()["revision"] == 2
        assert client.get(f"/api/trade/pi/{document_id}/reviews/{proposal_id}",
                          headers=headers).json()["status"] == "superseded"  # 대기 검토 무효화
        [row] = sources_of(client, document_id)
        assert (row.revision, row.file_id, row.origin, row.doc_kind) == (2, first["file_id"], "upload", "PI")

        replaced = client.put(f"/api/trade/pi/{document_id}/sources", headers=headers,
                              json={"revision": 2, "file_ids": [second["file_id"]]})
        assert replaced.status_code == 200 and replaced.json()["revision"] == 3
        rows = sources_of(client, document_id)
        assert [(row.revision, row.file_id) for row in rows] == [(2, first["file_id"]), (3, second["file_id"])]
        assert client.delete(f"/api/files/{first['file_id']}", headers=headers).status_code == 409  # 과거 revision 연결도 참조다


def test_other_users_files_and_documents_are_isolated(database_url):
    jwks, storage = FakeJwks(), FakeStorage()
    with make_client(database_url, jwks, storage) as client:
        alice, bob = bearer(jwks.token()), bearer(jwks.token(sub=uuid4()))
        mine = uploaded(client, alice)
        document = create_pi_document(client, bob)

        for method, path in (("get", f"/api/files/{mine['file_id']}"),
                             ("get", f"/api/files/{mine['file_id']}/download"),
                             ("delete", f"/api/files/{mine['file_id']}")):
            response = getattr(client, method)(path, headers=bob)
            assert response.status_code == 404, f"{method} {path}: {response.text}"  # 타인 파일은 없는 문서다

        response = client.put(f"/api/trade/pi/{document['document_id']}/sources", headers=bob,
                              json={"revision": document["revision"], "file_ids": [mine["file_id"]]})
        assert response.status_code == 422 and response.json()["error"]["code"] == "FILE_NOT_OWNED"
        assert client.put(f"/api/trade/pi/{document['document_id']}/sources", headers=alice,
                          json={"revision": document["revision"], "file_ids": [mine["file_id"]]}
                          ).status_code == 404  # 타인 문서


def test_storage_client_uses_official_endpoints_and_converts_errors(monkeypatch):
    """httpx 호출부 자체를 확인한다: 공식 엔드포인트·서버 키 헤더·오류 변환(가짜 HTTP로)."""
    import httpx

    from app.files.storage import StorageClient

    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/1/attachments/missing"):
            return httpx.Response(404)
        if url.endswith("/1/attachments/broken"):
            return httpx.Response(500)
        if url.endswith("/1/attachments/down"):
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, content=b"object-bytes")

    monkeypatch.setattr("app.files.storage.httpx.request", fake_request)
    client = StorageClient("https://fake-project.supabase.example", "fake-secret", "trade-files")

    client.upload("1/attachments/a", b"data", "application/pdf")
    client.download("1/attachments/a")
    assert [calls[0][0], calls[1][0]] == ["POST", "GET"]
    assert calls[0][1].endswith("/storage/v1/object/trade-files/1/attachments/a")
    assert calls[0][2]["headers"]["apikey"] == "fake-secret"
    assert calls[0][2]["headers"]["Authorization"] == "Bearer fake-secret"
    assert calls[0][2]["headers"]["Content-Type"] == "application/pdf"
    assert calls[0][2]["content"] == b"data"
    assert client.download("1/attachments/a") == b"object-bytes"

    client.delete("1/attachments/missing")  # 없는 객체 삭제는 멱등(예외 없음)
    with pytest.raises(StorageError) as broken:
        client.delete("1/attachments/broken")
    assert broken.value.code == "storage_http_error"
    with pytest.raises(StorageError) as unavailable:
        client.download("1/attachments/down")
    assert unavailable.value.code == "storage_unavailable"
    assert "fake-secret" not in str(broken.value) and "fake-secret" not in str(unavailable.value)


@pytest.mark.parametrize(("status", "body", "code"), [
    (409, {"code": "ResourceAlreadyExists"}, "object_exists"),
    (400, {"error": "Duplicate"}, "object_exists"),
    (404, {"code": "NoSuchKey"}, "object_not_found"),
    (400, {"error": "not_found"}, "object_not_found"),
    (500, {"code": "private-unknown-value"}, "storage_http_error"),
])
def test_storage_errors_expose_only_safe_codes(monkeypatch, status, body, code):
    import httpx
    from app.files.storage import StorageClient

    monkeypatch.setattr("app.files.storage.httpx.request", lambda *args, **kwargs:
                        httpx.Response(status, json={**body, "message": "secret-response"}))
    with pytest.raises(StorageError) as caught:
        StorageClient("https://storage.example.invalid", "fake-secret", "trade-files").upload(
            "1/issued/file", b"bytes", "application/pdf")
    assert caught.value.code == code and caught.value.status_code == status
    assert "secret-response" not in str(caught.value)


def test_cleanup_command_keeps_referenced_and_unknown_age_objects(database_url):
    jwks, storage = FakeJwks(), FakeStorage()
    with make_client(database_url, jwks, storage) as client:
        database = client.app.state.database
        headers = bearer(jwks.token())
        uploaded(client, headers)  # 참조 중인 객체는 절대 지우지 않는다
        referenced_key = file_rows(client)[0].object_key

        now = datetime.now(UTC)
        storage.objects["7/attachments/orphan-old"] = b"old"
        storage.objects["7/attachments/orphan-fresh"] = b"fresh"
        storage.objects["7/attachments/orphan-unknown"] = b"unknown"  # created_at 없음(나이 모름)
        storage.created_at["7/attachments/orphan-old"] = now - timedelta(hours=5)
        storage.created_at["7/attachments/orphan-fresh"] = now

        rows = cleanup.unreferenced_objects(database, storage)
        assert {row["key"] for row in rows} == {"7/attachments/orphan-old", "7/attachments/orphan-fresh",
                                                "7/attachments/orphan-unknown"}

        try:
            cleanup.execute(database, storage, older_than_hours=1, delete=True, confirmed=False)
            raised = False
        except SystemExit:
            raised = True
        assert raised  # 재확인(--yes) 없이는 지우지 않는다

        _, deleted = cleanup.execute(database, storage, older_than_hours=1, delete=True, confirmed=True)
        assert deleted == ["7/attachments/orphan-old"]  # 오래된 미참조 객체만 지운다
        assert set(storage.objects) == {referenced_key, "7/attachments/orphan-fresh",
                                        "7/attachments/orphan-unknown"}


def test_storage_listing_walks_folders_and_each_page(monkeypatch):
    import httpx
    from app.files import storage as module

    folder = lambda name: {"name": name, "id": None, "metadata": None, "created_at": None}
    file = lambda name: {"name": name, "id": "file-id", "metadata": {"size": 3},
                         "created_at": "2026-11-01T00:00:00Z"}
    pages = {"": [folder("1"), folder("2")], "1": [folder("issued"), folder("attachments")],
             "1/issued": [folder("proposal")], "1/issued/proposal": [file("pdf")],
             "1/attachments": [file("a"), file("b"), file("c")], "2": [folder("branding")],
             "2/branding": [file("seal")]}
    calls = []
    def request(method, url, **kwargs):
        query = kwargs["json"]
        calls.append((query["prefix"], query["offset"]))
        rows = pages[query["prefix"]]
        return httpx.Response(200, json=rows[query["offset"]:query["offset"] + query["limit"]])

    monkeypatch.setattr(module, "LIST_PAGE_SIZE", 2)
    monkeypatch.setattr(module.httpx, "request", request)
    rows = module.StorageClient("https://storage.example.invalid", "fake", "trade-files").list_objects()
    assert {row["name"] for row in rows} == {"1/issued/proposal/pdf", "1/attachments/a",
                                              "1/attachments/b", "1/attachments/c", "2/branding/seal"}
    assert ("1/attachments", 2) in calls
