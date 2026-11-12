"""계획 9절: 회사 로고·직인의 Storage 전환을 가짜 Storage·실제 PostgreSQL로 검증한다.

업로드는 file_assets+Storage에만 남고 DB 바이너리 열은 비워 둔다, 제안이 이미지 파일 ID/해시를
고정해 설정 교체 뒤에도 과거 제안은 같은 이미지를 쓴다, 참조 중 이미지 삭제는 거부된다,
Storage 장애·손상·이전 중(파일 ID 없는 옛 제안) 실패를 성공으로 돌려주지 않는다,
backfill은 해시를 유지하며 반복 실행이 안전하다. 실제 Supabase Storage HTTP는 부르지 않는다.

파일 삭제 API(/api/files)는 Bearer 전용이므로 이 파일의 클라이언트는 Bearer 토큰으로 호출한다.
"""
from hashlib import sha256

import pytest
from sqlalchemy import select

from app.db.models import CompanyBranding, FileAsset, TradeDocument, TradeDocumentVersion, TradeProposal, User
from app.files import cleanup
from app.trade.settings import backfill
from app.trade.settings.repository import resolve_company_seal
from tests.fakes.storage import FakeStorage, storage_error
from tests.test_files_storage import bearer, make_client
from tests.test_pi_domain import pi_input
from tests.test_supabase_auth import FakeJwks, write_settings
from tests.test_trade_flow import seal_png


def asset_rows(client):
    with client.app.state.database.session() as session:
        return list(session.scalars(select(FileAsset).order_by(FileAsset.id)))


def upload_image(client, headers, kind, data, name="image.png"):
    return client.post(f"/api/trade/settings/branding/{kind}", headers=headers,
                       files={"image": (name, data, "image/png")})


def create_pi(client, headers):
    response = client.post("/api/trade/pi", headers=headers, json=pi_input().model_dump(mode="json"))
    assert response.status_code == 201, response.text
    return response.json()


def propose(client, headers, document):
    response = client.post(f"/api/trade/pi/{document['document_id']}/reviews", headers=headers,
                           json={"revision": document["revision"]})
    assert response.status_code == 201, response.text
    return response.json()


def decide(client, headers, proposal, action="approve"):
    return client.post(f"/api/trade/pi/{proposal['document_id']}/reviews/{proposal['id']}/decisions",
                       headers=headers, json={"action": action, "revision": proposal["revision"],
                                              "content_hash": proposal["content_hash"]})


@pytest.fixture
def branding_client(database_url):
    """Bearer 인증 + 가짜 Storage로 설정→작성→검토→파일 API를 함께 쓰는 클라이언트."""
    jwks, storage = FakeJwks(), FakeStorage()
    with make_client(database_url, jwks, storage) as client:
        headers = bearer(jwks.token())
        write_settings(client, headers)
        assert upload_image(client, headers, "seal", seal_png()).status_code == 200
        yield client, headers


def test_branding_upload_keeps_bytes_only_in_storage_and_metadata_in_db(branding_client):
    client, headers = branding_client
    storage = client.app.state.storage
    [asset] = asset_rows(client)
    with client.app.state.database.session() as session:
        branding = session.get(CompanyBranding, 1)
        assert branding.seal_file_id == asset.id
        assert branding.seal is None and branding.logo is None  # 새 업로드는 DB 바이너리에 두지 않는다
    assert asset.sha256 == sha256(seal_png()).hexdigest()
    assert asset.object_key.startswith("1/branding/") and asset.content_type == "image/png"
    assert storage.objects[asset.object_key] == seal_png()  # bytes는 Storage에만 있다
    branding_view = client.get("/api/trade/settings", headers=headers).json()["branding"]
    assert branding_view == {"has_logo": False, "has_seal": True,
                             "logo_file_id": None, "seal_file_id": asset.id}
    # 브랜딩 객체는 file_assets 행이 가리키므로 미참조 정리 대상이 아니다.
    assert cleanup.unreferenced_objects(client.app.state.database, storage) == []


def test_settings_replacement_and_delete_attempts_keep_referenced_images(branding_client):
    client, headers = branding_client
    [first] = asset_rows(client)
    document = create_pi(client, headers)
    proposal = propose(client, headers, document)

    # 제안 후 삭제 시도: 회사 설정과 제안이 모두 참조 중이다.
    assert client.delete(f"/api/files/{first.id}", headers=headers).status_code == 409

    # 설정 교체: 새 직인은 새 파일이고, 과거 제안은 첫 직인을 그대로 고정한다.
    assert upload_image(client, headers, "seal", seal_png(2, 1), "new.png").status_code == 200
    first_again, second = asset_rows(client)
    with client.app.state.database.session() as session:
        assert session.get(CompanyBranding, 1).seal_file_id == second.id
    assert client.delete(f"/api/files/{first.id}", headers=headers).status_code == 409  # 제안이 아직 참조 중
    approved = decide(client, headers, proposal).json()
    assert approved["status"] == "approved" and approved["payload"]["seal_sha256"] == first.sha256

    # 승인된 제안도 이미지를 계속 가리킨다(사용 중인 과거 직인 삭제 금지). 새 직인은 설정이 참조 중이다.
    assert client.delete(f"/api/files/{first.id}", headers=headers).status_code == 409
    assert client.delete(f"/api/files/{second.id}", headers=headers).status_code == 409


def test_logo_replacement_leaves_orphan_asset_deletable_and_new_proposal_uses_it(branding_client):
    client, headers = branding_client
    assert upload_image(client, headers, "logo", seal_png(3, 1), "logo.png").status_code == 200
    first_logo = asset_rows(client)[-1]
    assert upload_image(client, headers, "logo", seal_png(4, 1), "logo2.png").status_code == 200
    assert client.delete(f"/api/files/{first_logo.id}", headers=headers).status_code == 204  # 아무도 참조 안 함

    proposal = propose(client, headers, create_pi(client, headers))
    with client.app.state.database.session() as session:
        row = session.get(TradeProposal, proposal["id"])
        assert row.logo_file_id is not None  # 새 제안은 새 로고를 고정한다
        assert row.logo_file_id != first_logo.id


def test_storage_failures_are_not_reported_as_success(branding_client):
    client, headers = branding_client
    storage = client.app.state.storage
    document = create_pi(client, headers)

    storage.download_error = storage_error()
    failed = client.post(f"/api/trade/pi/{document['document_id']}/reviews", headers=headers,
                         json={"revision": document["revision"]})
    assert failed.status_code == 503 and failed.json()["error"]["code"] == "STORAGE_UNAVAILABLE"

    storage.download_error = None
    proposal = propose(client, headers, document)
    storage.download_error = storage_error()
    decision = decide(client, headers, proposal)
    assert decision.status_code == 503 and decision.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
    with client.app.state.database.session() as session:
        assert session.get(TradeProposal, proposal["id"]).status == "pending"  # 승인된 것이 아니다


def test_corrupted_and_missing_images_are_not_rendered(branding_client):
    client, headers = branding_client
    storage = client.app.state.storage
    [asset] = asset_rows(client)
    document = create_pi(client, headers)

    storage.objects[asset.object_key] = b"tampered"  # 기록된 해시와 달라졌다
    corrupted = client.post(f"/api/trade/pi/{document['document_id']}/reviews", headers=headers,
                            json={"revision": document["revision"]})
    assert corrupted.status_code == 503 and corrupted.json()["error"]["code"] == "IMAGE_CORRUPTED"
    storage.objects[asset.object_key] = seal_png()

    proposal = propose(client, headers, document)
    with client.app.state.database.session() as session:  # backfill 전 옛 제안 상태를 만든다
        session.get(TradeProposal, proposal["id"]).seal_file_id = None
    legacy = decide(client, headers, proposal)
    assert legacy.status_code == 503 and legacy.json()["error"]["code"] == "IMAGE_UNAVAILABLE"


def legacy_rows(database):
    """9절 이전 상태: 설정·제안이 이미지를 DB 바이너리로만 가진다."""
    seal, logo = seal_png(), seal_png(3, 1)
    with database.session() as session:
        session.add(User(id=2, google_sub="fake-sub-2", email="demo2@example.invalid"))
        session.flush()
        session.add(CompanyBranding(user_id=1, seal=seal, logo=logo,
                                    seal_sha256=sha256(seal).hexdigest()))
        session.add(CompanyBranding(user_id=2, seal=b"broken-seal", seal_sha256="0" * 64))
        document = TradeDocument(user_id=1, thread_id="legacy-thread", run_id="legacy-run",
                                 doc_kind="PI", doc_no="PI-OLD", draft={}, revision=1, status="issued")
        session.add(document)
        session.flush()
        session.add(TradeDocumentVersion(document_id=document.id, revision=1, payload={}, user_id=1))
        session.add(TradeProposal(id="legacyproposal", user_id=1, document_id=document.id, revision=1,
                                  payload={"seal_sha256": sha256(seal).hexdigest(), "logo_sha256": None},
                                  content_hash="0" * 64, status="approved", seal=seal))
    return seal, logo


def test_backfill_moves_binaries_with_same_hash_and_is_safe_to_rerun(database):
    seal, logo = legacy_rows(database)
    storage = FakeStorage()

    plan = backfill.backfill(database, storage)  # dry-run: 계획만 보고 상태를 바꾸지 않는다
    assert plan["linked"] == 3 and plan["uploaded"] == 2  # 설정 직인·로고 + 제안 직인(재사용)
    assert plan["skipped"] == ["CompanyBranding(user_id=2) seal: 해시 불일치"]
    with database.session() as session:
        assert session.get(CompanyBranding, 1).seal_file_id is None
        assert session.scalars(select(FileAsset)).all() == []
    assert storage.objects == {}

    done = backfill.backfill(database, storage, confirmed=True)
    assert done["linked"] == 3 and done["uploaded"] == 2 and done["skipped"] == plan["skipped"]
    with database.session() as session:
        assets = {row.sha256: row for row in session.scalars(select(FileAsset))}
        assert set(assets) == {sha256(seal).hexdigest(), sha256(logo).hexdigest()}
        branding = session.get(CompanyBranding, 1)
        assert branding.seal_file_id == assets[sha256(seal).hexdigest()].id
        assert branding.logo_file_id == assets[sha256(logo).hexdigest()].id
        assert session.get(TradeProposal, "legacyproposal").seal_file_id == branding.seal_file_id
        assert session.get(CompanyBranding, 2).seal_file_id is None  # 해시 불일치 행은 그대로
    assert {storage.objects[row.object_key] for row in assets.values()} == {seal, logo}  # 같은 bytes
    assert resolve_company_seal(1, database=database, storage=storage) == (seal, None)

    repeated = backfill.backfill(database, storage, confirmed=True)  # 반복 실행은 아무 것도 바꾸지 않는다
    assert repeated["linked"] == 0 and repeated["uploaded"] == 0
    with database.session() as session:
        assert len(session.scalars(select(FileAsset)).all()) == 2
