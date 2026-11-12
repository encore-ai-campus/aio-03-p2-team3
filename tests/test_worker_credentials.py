"""실제 OS 저장소를 사용한다. Windows CI는 DPAPI·DACL과 별도 프로세스 읽기를 확인한다."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
import os
import subprocess
import sys
from uuid import uuid4

import pytest

from app.worker import credentials
from app.worker.pc import LocalPolicy, read_credentials, save_credentials
from app.worker.protocol import MAX_JSON_BYTES, WorkerError


@pytest.fixture
def credential(tmp_path):
    policy = LocalPolicy("https://service.example.invalid", "fake-sub-owner", "fake-local-key")
    value = dict(device_id=str(uuid4()), device_token="fake-private-token-" + "x" * 32,
                 google_sub=policy.owner, expires_at=(datetime.now(UTC) + timedelta(days=1)).isoformat())
    return tmp_path / "한글 장치 토큰.json", policy, value


def test_credentials_roundtrip_and_separate_process(credential):
    path, policy, value = credential
    save_credentials(path, policy, value)
    assert read_credentials(path, policy) == {**value, "service": policy.service}
    if os.name == "nt":
        assert path.read_bytes().startswith(credentials._WINDOWS_MAGIC)
        assert value["device_token"].encode() not in path.read_bytes()
        assert policy.key.encode() not in path.read_bytes()
    else:
        assert path.stat().st_mode & 0o777 == 0o600
    result = subprocess.run([sys.executable, "-c", """
import sys
from app.worker.pc import LocalPolicy, read_credentials
policy = LocalPolicy('https://service.example.invalid', 'fake-sub-owner', 'unused')
data = read_credentials(sys.argv[1], policy)
assert data['device_id'] == sys.argv[2]
assert data['device_token'].startswith('fake-private-token-')
print('credential verified')
""", str(path), value["device_id"]], check=True, capture_output=True, text=True)
    assert result.stdout.strip() == "credential verified"
    assert value["device_token"] not in result.stdout + result.stderr


def test_existing_file_is_never_overwritten(credential):
    path, policy, value = credential
    save_credentials(path, policy, value)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        save_credentials(path, policy, {**value, "device_token": "different-token"})
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", [{"owner": "different-sub"}, {"service": "https://other.example.invalid"}])
def test_credentials_bind_to_explicit_owner_and_service(credential, change):
    path, policy, value = credential
    save_credentials(path, policy, value)
    with pytest.raises(WorkerError, match="owner_mismatch"):
        read_credentials(path, replace(policy, **change))


def test_expired_credentials_require_new_pairing(credential):
    path, policy, value = credential
    save_credentials(path, policy, {**value, "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()})
    with pytest.raises(WorkerError, match="expired"):
        read_credentials(path, policy)


def test_symlink_credentials_are_rejected_for_read_and_write(credential):
    path, policy, value = credential
    save_credentials(path, policy, value)
    link = path.with_name("credential-link")
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip("현재 Windows 계정에 symlink 생성 권한 없음; DACL/reparse 검증은 별도 검사")
    with pytest.raises((WorkerError, OSError)):
        read_credentials(link, policy)
    with pytest.raises((WorkerError, OSError)):
        save_credentials(link, policy, value)


def test_oversized_file_is_rejected_before_decoding(credential):
    path, policy, value = credential
    save_credentials(path, policy, value)
    path.write_bytes(b"x" * (MAX_JSON_BYTES + 1))
    with pytest.raises(WorkerError, match="credentials_unavailable"):
        read_credentials(path, policy)


@pytest.mark.skipif(os.name != "nt", reason="실제 Windows DPAPI/DACL 검사")
def test_windows_plaintext_and_tampered_dpapi_are_rejected(credential):
    path, policy, value = credential
    save_credentials(path, policy, value)
    protected = path.read_bytes()
    path.write_bytes(json.dumps({**value, "service": policy.service}).encode())
    with pytest.raises(WorkerError, match="credentials_unavailable"):
        read_credentials(path, policy)
    path.write_bytes(protected[:-1] + bytes([protected[-1] ^ 1]))
    with pytest.raises(WorkerError, match="credentials_unavailable"):
        read_credentials(path, policy)


@pytest.mark.skipif(os.name != "nt", reason="실제 Windows DACL 검사")
def test_windows_acl_with_other_readers_is_rejected(credential):
    path, policy, value = credential
    save_credentials(path, policy, value)
    # 실제 Everyone 읽기 ACE를 추가한다. 지역화된 그룹 이름에 의존하지 않는다.
    subprocess.run(["icacls", str(path), "/grant", "*S-1-1-0:(R)"], check=True, capture_output=True)
    with pytest.raises(WorkerError, match="credentials_unavailable"):
        read_credentials(path, policy)


@pytest.mark.skipif(os.name != "posix", reason="POSIX 소유자/600 권한 검사")
def test_posix_world_readable_credentials_are_rejected(credential):
    path, policy, value = credential
    save_credentials(path, policy, value)
    path.chmod(0o644)
    with pytest.raises(WorkerError, match="unauthorized"):
        read_credentials(path, policy)
