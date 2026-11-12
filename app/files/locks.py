"""발급 객체 재사용·수동 삭제를 여러 서버에서도 같은 트랜잭션 잠금으로 조율한다."""
from hashlib import sha256

from sqlalchemy import text


def lock_object(session, object_key: str) -> None:
    lock_id = int.from_bytes(sha256(object_key.encode()).digest()[:8], "big", signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
