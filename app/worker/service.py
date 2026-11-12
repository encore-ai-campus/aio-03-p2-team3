"""DB로 직렬화하는 장치/작업 상태 전이. 트랜잭션 안에서 네트워크를 기다리지 않는다."""
from datetime import timedelta
import hashlib
import hmac
import secrets
from uuid import uuid4

from sqlalchemy import delete, or_, select, update

from app.db.models import User, WorkerDevice, WorkerJob, WorkerPairing, WorkerRateLimit, utcnow
from app.worker.protocol import WorkerError, digest, validate_capabilities, validate_request, validate_result

SCOPES = ["ai:claim", "ai:complete"]
PENDING = ("queued", "leased")


def secret_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def rate_limit(database, identity, action, limit, seconds, *, now=None):
    """재시작/여러 프로세스가 공유하는 고정 시간 창. 인증 실패도 별도 트랜잭션에 센다."""
    now = now or utcnow()
    window = int(now.timestamp()) // seconds
    key = secret_hash(f"{action}:{identity}")
    values = dict(key=key, window=window, count=0, expires_at=now + timedelta(seconds=seconds * 2))
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    insert = sqlite_insert if database.engine.dialect.name == "sqlite" else pg_insert
    with database.session() as session:
        session.execute(insert(WorkerRateLimit).values(**values).on_conflict_do_nothing())
        accepted = session.execute(update(WorkerRateLimit).where(
            WorkerRateLimit.key == key, WorkerRateLimit.window == window,
            WorkerRateLimit.count < limit,
        ).values(count=WorkerRateLimit.count + 1)).rowcount
    if not accepted:
        raise WorkerError("rate_limit", 429)


def _lock_user(session, user_id):
    # UPDATE는 SQLite에서도 쓰기 잠금을 획득한다. PG도 같은 사용자 행으로 직렬화한다.
    if session.execute(update(User).where(User.id == user_id).values(id=User.id)).rowcount != 1:
        raise WorkerError("unauthorized", 401)
    return session.get(User, user_id, populate_existing=True)


def _finish(session, condition, status, error, now):
    session.execute(update(WorkerJob).where(condition, WorkerJob.status.in_(PENDING)).values(
        status=status, error_kind=error, payload=None, finished_at=now, lease_expires_at=None))


def _revoke(session, user_id, now):
    session.execute(update(WorkerDevice).where(
        WorkerDevice.user_id == user_id, WorkerDevice.revoked_at.is_(None),
    ).values(revoked_at=now))
    session.execute(update(WorkerPairing).where(
        WorkerPairing.user_id == user_id, WorkerPairing.consumed_at.is_(None),
    ).values(expires_at=now))
    _finish(session, WorkerJob.user_id == user_id, "cancelled", "worker_unavailable", now)


def _cleanup_user(session, user_id, now):
    expired_ids = select(WorkerDevice.id).where(
        WorkerDevice.user_id == user_id, WorkerDevice.expires_at <= now)
    _finish(session, WorkerJob.device_id.in_(expired_ids), "expired", "expired", now)
    session.execute(update(WorkerDevice).where(
        WorkerDevice.user_id == user_id, WorkerDevice.revoked_at.is_(None), WorkerDevice.expires_at <= now,
    ).values(revoked_at=now))
    _finish(session, (WorkerJob.user_id == user_id) & or_(
        WorkerJob.expires_at <= now,
        (WorkerJob.status == "leased") & (WorkerJob.lease_expires_at <= now),
    ), "expired", "expired", now)


def cleanup(database, *, now=None):
    now = now or utcnow()
    with database.session() as session:
        ids = list(session.scalars(select(User.id).where(or_(
            User.id.in_(select(WorkerDevice.user_id)), User.id.in_(select(WorkerJob.user_id)),
        ))))
    for user_id in ids:
        with database.session() as session:
            _lock_user(session, user_id)
            _cleanup_user(session, user_id, now)
    with database.session() as session:
        session.execute(delete(WorkerPairing).where(WorkerPairing.expires_at <= now))
        session.execute(delete(WorkerRateLimit).where(WorkerRateLimit.expires_at <= now))


def start_pairing(database, request, model, *, now=None):
    now = now or utcnow()
    capabilities = validate_capabilities(request.capabilities, model)
    secret, code, pairing_id = secrets.token_urlsafe(32), secrets.token_urlsafe(18), str(uuid4())
    with database.session() as session:
        session.add(WorkerPairing(id=pairing_id, secret_hash=secret_hash(secret), code_hash=secret_hash(code),
                                 device_name=request.device_name.strip(), capabilities=capabilities,
                                 created_at=now, expires_at=now + timedelta(minutes=10)))
    return dict(pairing_id=pairing_id, device_secret=secret, pairing_code=code,
                expires_at=(now + timedelta(minutes=10)).isoformat(), poll_interval_seconds=5)


def approve_pairing(database, user_id, code, device_name, *, now=None):
    now = now or utcnow()
    with database.session() as session:
        user = _lock_user(session, user_id)
        if user.last_login_at is None or user.ai_execution_mode != "local_worker":
            raise WorkerError("owner_mismatch", 403)
        pair = session.scalar(select(WorkerPairing).where(WorkerPairing.code_hash == secret_hash(code)))
        if pair is None or pair.device_name != device_name:
            raise WorkerError("pairing_invalid", 404)
        # 같은 코드를 쓰는 다른 사용자의 승인도 조건부 갱신으로 거부한다.
        changed = session.execute(update(WorkerPairing).where(
            WorkerPairing.id == pair.id, WorkerPairing.user_id.is_(None),
            WorkerPairing.approved_at.is_(None), WorkerPairing.consumed_at.is_(None),
            WorkerPairing.expires_at > now,
        ).values(user_id=user_id, approved_at=now)).rowcount
        if changed != 1:
            raise WorkerError("pairing_invalid", 409)
    return {"status": "approved"}


def poll_pairing(database, pairing_id, secret, *, now=None):
    now = now or utcnow()
    # 소유자 조회 뒤 사용자 잠금 → pairing 잠금 순서로 해제/모드 변경과 경쟁을 막는다.
    with database.session() as session:
        owner = session.scalar(select(WorkerPairing.user_id).where(WorkerPairing.id == pairing_id))
    with database.session() as session:
        user = _lock_user(session, owner) if owner is not None else None
        pair = session.scalar(select(WorkerPairing).where(WorkerPairing.id == pairing_id).with_for_update())
        if pair is None or not hmac.compare_digest(pair.secret_hash, secret_hash(secret)):
            raise WorkerError("unauthorized", 401)
        if pair.expires_at <= now or pair.consumed_at is not None:
            raise WorkerError("expired", 410)
        # SQLite에서도 동시 조회 중 한 요청만 자격증명을 발급한다.
        changed = session.execute(update(WorkerPairing).where(
            WorkerPairing.id == pair.id, WorkerPairing.consumed_at.is_(None),
            or_(WorkerPairing.last_polled_at.is_(None), WorkerPairing.last_polled_at <= now - timedelta(seconds=5)),
        ).values(last_polled_at=now)).rowcount
        if changed != 1:
            raise WorkerError("rate_limit", 429)
        if pair.approved_at is None:
            return {"status": "pending"}
        # 처음 읽은 뒤 승인됐으면 다음 5초 조회에서 사용자 잠금을 획득한다.
        if user is None:
            return {"status": "pending"}
        if user.ai_execution_mode != "local_worker" or user.last_login_at is None:
            raise WorkerError("worker_unavailable", 409)
        _revoke(session, user.id, now)
        # _revoke는 이전 승인 대기도 만료시킨다. 현재 연결만 소비한 채 원래 만료로 복원한다.
        pair.expires_at = pair.created_at + timedelta(minutes=10)
        pair.consumed_at = now
        token, device_id = secrets.token_urlsafe(32), str(uuid4())
        session.add(WorkerDevice(id=device_id, user_id=user.id, name=pair.device_name,
                                 token_hash=secret_hash(token), scopes=SCOPES, capabilities=pair.capabilities,
                                 created_at=now, last_seen_at=now, expires_at=now + timedelta(days=30)))
        return dict(status="connected", device_id=device_id, device_token=token,
                    google_sub=user.google_sub, scopes=SCOPES,
                    expires_at=(now + timedelta(days=30)).isoformat())


def set_mode(database, user_id, mode, *, now=None):
    if mode not in {"stored_key", "local_worker"}:
        raise WorkerError()
    now = now or utcnow()
    with database.session() as session:
        user = _lock_user(session, user_id)
        if user.last_login_at is None:
            raise WorkerError("owner_mismatch", 403)
        if user.ai_execution_mode != mode:
            _revoke(session, user_id, now)
            user.ai_execution_mode = mode
    return {"ai_execution_mode": mode, "ai_ready": False if mode == "local_worker" else None}


def disconnect(database, user_id, device_id, *, now=None):
    now = now or utcnow()
    with database.session() as session:
        _lock_user(session, user_id)
        row = session.get(WorkerDevice, device_id)
        if row is None or row.user_id != user_id:
            raise WorkerError("not_found", 404)
        _revoke(session, user_id, now)
    return {"status": "disconnected"}


def status(database, user_id, *, now=None):
    now = now or utcnow()
    with database.session() as session:
        user = _lock_user(session, user_id)
        _cleanup_user(session, user_id, now)
        devices = session.scalars(select(WorkerDevice).where(
            WorkerDevice.user_id == user_id, WorkerDevice.revoked_at.is_(None))).all()
        jobs = session.scalars(select(WorkerJob).where(
            WorkerJob.user_id == user_id).order_by(WorkerJob.created_at.desc()).limit(20)).all()
        return dict(ai_execution_mode=user.ai_execution_mode, ai_ready=False if user.ai_execution_mode == "local_worker" else None,
                    integration="pending_section_4", devices=[dict(device_id=d.id, name=d.name,
                    expires_at=d.expires_at.isoformat(), last_seen_at=d.last_seen_at.isoformat(),
                    status="online" if d.last_seen_at > now - timedelta(seconds=45) else "offline") for d in devices],
                    jobs=[dict(job_id=j.id, attempt_id=j.attempt_id, status=j.status,
                               error_kind=j.error_kind) for j in jobs])


def _authenticate(session, device_id, token, now):
    row = session.get(WorkerDevice, device_id)
    if row is None or not token or not hmac.compare_digest(row.token_hash, secret_hash(token)):
        raise WorkerError("unauthorized", 401)
    user = _lock_user(session, row.user_id)
    session.refresh(row)
    if row.revoked_at is not None or row.expires_at <= now or user.ai_execution_mode != "local_worker" or row.scopes != SCOPES:
        raise WorkerError("unauthorized", 401)
    return row


def enqueue(database, user_id, *, prompt_id, prompt_version, schema_id, schema_version,
            variables, requested_model, run_id, model, now=None):
    """인증된 서버 업무 전용 진입점. HTTP/장치에는 작업 생성 권한을 제공하지 않는다.

    3절에서는 기존 그래프/문서에 연결하지 않는다. 재시도는 자동 생성하지 않는다.
    """
    now = now or utcnow()
    with database.session() as session:
        user = _lock_user(session, user_id)
        _cleanup_user(session, user_id, now)
        device = session.scalar(select(WorkerDevice).where(
            WorkerDevice.user_id == user_id, WorkerDevice.revoked_at.is_(None), WorkerDevice.expires_at > now))
        if user.ai_execution_mode != "local_worker" or device is None or device.last_seen_at <= now - timedelta(seconds=45):
            raise WorkerError("worker_unavailable", 409)
        if session.scalar(select(WorkerJob.id).where(WorkerJob.user_id == user_id, WorkerJob.status.in_(PENDING)).offset(31)):
            raise WorkerError("rate_limit", 429)
        job_id, attempt_id = str(uuid4()), str(uuid4())
        expires = now + timedelta(seconds=120)
        payload = dict(protocol_version=1, kind="structured_ai_call", job_id=job_id, attempt_id=attempt_id,
                       device_id=device.id, run_id=run_id, prompt_id=prompt_id, prompt_version=prompt_version,
                       schema_id=schema_id, schema_version=schema_version, variables=variables,
                       requested_model=requested_model, created_at=now.isoformat(), expires_at=expires.isoformat())
        validate_request(payload, device.capabilities, model)
        session.add(WorkerJob(id=job_id, attempt_id=attempt_id, device_id=device.id, user_id=user_id,
                              run_id=run_id, schema_id=schema_id, schema_version=schema_version,
                              payload=payload, created_at=now, expires_at=expires))
        return payload


def claim(database, device_id, token, model, *, now=None):
    now = now or utcnow()
    with database.session() as session:
        device = _authenticate(session, device_id, token, now)
        _cleanup_user(session, device.user_id, now)
        device.last_seen_at = now
        # 한 장치에서 실행 중인 시도는 하나다.
        if session.scalar(select(WorkerJob.id).where(WorkerJob.device_id == device.id, WorkerJob.status == "leased")):
            return {"job": None}
        row = session.scalar(select(WorkerJob).where(
            WorkerJob.user_id == device.user_id, WorkerJob.device_id == device.id,
            WorkerJob.status == "queued", WorkerJob.expires_at > now,
        ).order_by(WorkerJob.created_at, WorkerJob.id).limit(1))
        if row is None:
            return {"job": None}
        validate_request(row.payload, device.capabilities, model)
        changed = session.execute(update(WorkerJob).where(
            WorkerJob.id == row.id, WorkerJob.status == "queued", WorkerJob.attempt_id == row.attempt_id,
        ).values(status="leased", lease_expires_at=min(now + timedelta(seconds=30), row.expires_at), heartbeat_at=now)).rowcount
        return {"job": row.payload if changed == 1 else None}


def _owned_job(session, device, job_id, attempt_id):
    row = session.get(WorkerJob, job_id)
    if row is None or (row.user_id, row.device_id, row.attempt_id) != (device.user_id, device.id, attempt_id):
        raise WorkerError("not_found", 404)
    return row


def heartbeat(database, device_id, token, job_id, attempt_id, *, now=None):
    now = now or utcnow()
    with database.session() as session:
        device = _authenticate(session, device_id, token, now)
        row = _owned_job(session, device, job_id, attempt_id)
        if row.status != "leased" or row.expires_at <= now or row.lease_expires_at <= now:
            raise WorkerError("expired", 410)
        if row.heartbeat_at > now - timedelta(seconds=10):
            raise WorkerError("rate_limit", 429)
        row.heartbeat_at, row.lease_expires_at = now, min(now + timedelta(seconds=30), row.expires_at)
        device.last_seen_at = now
        return {"lease_expires_at": row.lease_expires_at.isoformat()}


def complete(database, device_id, token, job_id, value, *, now=None):
    now = now or utcnow()
    with database.session() as session:
        device = _authenticate(session, device_id, token, now)
        row = _owned_job(session, device, job_id, value.get("attempt_id"))
        result = validate_result(value, row.schema_id, row.schema_version)
        if (result.job_id, result.device_id) != (row.id, device.id):
            raise WorkerError("not_found", 404)
        fingerprint = digest(value)
        if row.status in {"succeeded", "failed"} and row.result_hash == fingerprint:
            return {"status": row.status, "duplicate": True}
        if row.status != "leased" or row.expires_at <= now or row.lease_expires_at <= now:
            raise WorkerError("expired", 410)
        state = "succeeded" if result.ok else "failed"
        changed = session.execute(update(WorkerJob).where(
            WorkerJob.id == row.id, WorkerJob.user_id == device.user_id, WorkerJob.device_id == device.id,
            WorkerJob.attempt_id == result.attempt_id, WorkerJob.status == "leased",
            WorkerJob.expires_at > now, WorkerJob.lease_expires_at > now,
        ).values(status=state, error_kind=None if result.ok else result.error_kind, result_hash=fingerprint,
                 payload=None, finished_at=now, lease_expires_at=None)).rowcount
        if changed != 1:
            raise WorkerError("expired", 410)
        device.last_seen_at = now
        return {"status": state, "duplicate": False}


def cancel(database, user_id, job_id, *, now=None):
    now = now or utcnow()
    with database.session() as session:
        _lock_user(session, user_id)
        row = session.get(WorkerJob, job_id)
        if row is None or row.user_id != user_id:
            raise WorkerError("not_found", 404)
        if row.status not in (*PENDING, "cancelled"):
            raise WorkerError("job_finished", 409)
        _finish(session, WorkerJob.id == job_id, "cancelled", "worker_unavailable", now)
    return {"status": "cancelled"}
