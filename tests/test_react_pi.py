"""React PI에 추가한 읽기 전용 검토 이미지·개인 키 API의 권한과 비밀값 경계."""
from hashlib import sha256
from uuid import uuid4

from cryptography.fernet import Fernet

from app.config import Settings
from app.db.models import UserOpenAIKey
from tests.fakes.storage import FakeStorage
from tests.test_files_storage import bearer, create_pi_document, make_client
from tests.test_supabase_auth import FakeJwks
from tests.test_trade_flow import seal_png


def test_review_preview_is_owned_frozen_and_does_not_issue_files(database_url):
    jwks, storage = FakeJwks(), FakeStorage()
    with make_client(database_url, jwks, storage) as client:
        owner, other = bearer(jwks.token()), bearer(jwks.token(sub=uuid4()))
        created = create_pi_document(client, owner)
        base = f"/api/trade/pi/{created['document_id']}/reviews"
        proposal = client.post(base, headers=owner, json={"revision": 1}).json()
        path = f"{base}/{proposal['id']}/branding/seal"
        response = client.get(path, headers=owner)
        assert response.status_code == 200 and response.content == seal_png()
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.headers['etag'] == f'"{sha256(response.content).hexdigest()}"'
        assert client.get(path, headers=other).status_code == 404
        assert client.get(path).status_code == 401
        assert client.get(path.replace('/pi/', '/po/'), headers=owner).status_code == 404
        assert client.get(path.replace(f"/{created['document_id']}/", '/999999/'), headers=owner).status_code == 404
        assert client.get(path.removesuffix('seal') + 'logo', headers=owner).status_code == 404
        client.delete('/api/trade/settings/branding/seal', headers=owner)
        assert client.get(path, headers=owner).content == response.content
        current = client.get(f"/api/trade/pi/{created['document_id']}", headers=owner).json()
        assert current['status'] == 'ready' and not current['files']
        issued = client.post(f"{base}/{proposal['id']}/decisions", headers=owner, json={
            'action': 'approve', 'revision': 1, 'content_hash': proposal['content_hash']})
        assert issued.status_code == 200, issued.text
        for file in issued.json()['files']:
            content = client.get(file['download_url'], headers=owner).content
            assert sha256(content).hexdigest() == file['content_hash']
        assert client.get(base + f"/{proposal['id']}", headers=owner).json()['payload'] == proposal['payload']


def test_bearer_key_management_encrypts_only_owner_key_and_never_echoes_input(database_url):
    jwks = FakeJwks()
    settings = Settings(database_url=database_url, session_secret='fake-key-session',
                        token_encryption_key=Fernet.generate_key().decode())
    with make_client(database_url, jwks, FakeStorage(), settings=settings) as client:
        owner, other = bearer(jwks.token()), bearer(jwks.token(sub=uuid4()))
        owner_id = client.get('/api/me', headers=owner).json()['user_id']
        key = 'sk-fake-for-local-test-only'
        assert client.put('/api/openai-key', data={'api_key': key}).status_code == 401
        saved = client.put('/api/openai-key', headers=owner, data={'api_key': key})
        assert saved.status_code == 200 and saved.json() == {'registered': True}
        assert saved.headers['cache-control'] == 'private, no-store' and key not in saved.text
        with client.app.state.database.session() as session:
            row = session.get(UserOpenAIKey, owner_id)
            assert row.api_key_enc != key
            assert client.app.state.google_access.cipher.decrypt(row.api_key_enc) == key
        for invalid in ('sk fake-input-with-space', 'sk-' + 'x' * 513):
            response = client.put('/api/openai-key', headers=owner, data={'api_key': invalid})
            assert response.status_code == 400 and invalid not in response.text
        assert client.delete('/api/openai-key', headers=other).json() == {'registered': False}
        with client.app.state.database.session() as session:
            assert session.get(UserOpenAIKey, owner_id) is not None
        assert client.delete('/api/openai-key', headers=owner).json() == {'registered': False}
        with client.app.state.database.session() as session:
            assert session.get(UserOpenAIKey, owner_id) is None
