"""Bearer Calendar 연결. Gmail/legacy callback과 서비스·토큰·state를 분리한다."""
from datetime import timedelta
from hashlib import sha256
import secrets

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.auth.gmail import GmailConnectionError
from app.auth.supabase import bearer_user_id
from app.clients.calendar import CalendarDenied, missing_calendar_scopes
from app.clients.gmail import GoogleError, TokenExpired
from app.db.models import CalendarOAuthAttempt, CalendarToken, User
from app.services.auth import ACCESS_TOKEN_MARGIN, make_cipher, utcnow

router = APIRouter(prefix="/api/calendar", tags=["calendar-connection"])
STATE_TTL_SECONDS = 600


def _digest(state):
    return sha256(state.encode()).hexdigest()


def _to_app(notice):
    return RedirectResponse(f"/app/settings?calendar={notice}", status_code=303)


def _start(request, user_id, google_sub, consent=False):
    access = request.app.state.calendar_access
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    with access.database.session() as session:
        session.get(User, user_id, with_for_update=True)
        session.execute(delete(CalendarOAuthAttempt).where(
            (CalendarOAuthAttempt.expires_at <= utcnow()) | (CalendarOAuthAttempt.user_id == user_id)))
        session.add(CalendarOAuthAttempt(
            state_hash=_digest(state), user_id=user_id, google_sub=google_sub,
            verifier_enc=access.cipher.encrypt(verifier), consent=consent,
            expires_at=utcnow() + timedelta(seconds=STATE_TTL_SECONDS)))
    request.session["oauth"] = {"service": "calendar", "state": state}
    return access.google.authorization_url(state, verifier, consent=consent)


@router.post("/connect")
def connect(request: Request, user_id: int = Depends(bearer_user_id)):
    settings = request.app.state.settings
    fields = ("google_oauth_client_id", "google_oauth_client_secret", "google_oauth_redirect_uri",
              "session_secret", "supabase_secret_key")
    if any(not getattr(settings, field) for field in fields) or make_cipher(settings) is None:
        raise GmailConnectionError(503, "config_missing", "서버의 Calendar 연결 설정이 끝나지 않았습니다.")
    _, _, token = request.headers.get("authorization", "").partition(" ")
    verified = request.app.state.supabase_auth.verify(token.strip())
    subject = request.app.state.supabase_auth.provider_google_subject(verified.sub)
    if not subject:
        raise GmailConnectionError(409, "google_identity_required", "Google로 다시 로그인해 본인 계정을 확인해 주세요.")
    return {"authorization_url": _start(request, user_id, subject)}


@router.post("/disconnect")
def disconnect(request: Request, user_id: int = Depends(bearer_user_id)):
    # Google revoke는 같은 클라이언트의 Gmail grant까지 폐기하므로 여기서는 호출하지 않는다.
    with request.app.state.database.session() as session:
        session.get(User, user_id, with_for_update=True)
        session.execute(delete(CalendarToken).where(CalendarToken.user_id == user_id))
        session.execute(delete(CalendarOAuthAttempt).where(CalendarOAuthAttempt.user_id == user_id))
    if request.session.get("oauth", {}).get("service") == "calendar":
        request.session.pop("oauth", None)
    return {"connected": False}


def complete_callback(request, pending, state, code, error):
    access = request.app.state.calendar_access
    if not state or not secrets.compare_digest(state, pending.get("state", "")):
        # 변조된 콜백도 원래 대기 state를 소비한다.
        if pending.get("state"):
            with access.database.session() as session:
                session.execute(delete(CalendarOAuthAttempt).where(
                    CalendarOAuthAttempt.state_hash == _digest(pending["state"])))
        return _to_app("login_failed")
    # 원자적 소비는 쿠키 재생·동시 콜백에도 딱 한 요청만 코드를 교환하게 한다.
    # 소비된 행은 최종 저장까지 남겨 해제/새 연결이 진행 중 콜백도 취소할 수 있게 한다.
    with access.database.session() as session:
        attempt = session.scalars(update(CalendarOAuthAttempt).where(
            CalendarOAuthAttempt.state_hash == _digest(state),
            CalendarOAuthAttempt.consumed.is_(False)).values(consumed=True)
            .returning(CalendarOAuthAttempt)).first()
    if attempt is None:
        return _to_app("login_failed")
    if attempt.expires_at <= utcnow():
        return _to_app("expired")
    if error or not code:
        return _to_app("cancelled" if error == "access_denied" else "login_failed")
    if access.cipher is None:
        return _to_app("config_missing")
    try:
        login = access.google.exchange_code(code, access.cipher.decrypt(attempt.verifier_enc))
        if login.sub != attempt.google_sub:
            return _to_app("different_account")
        if missing_calendar_scopes(login.scopes):
            return _to_app("scope_missing")
        if not login.refresh_token:
            if attempt.consent:
                return _to_app("refresh_missing")
            return RedirectResponse(_start(request, attempt.user_id, attempt.google_sub, consent=True),
                                    status_code=303)
        if not login.access_token or login.expires_at <= utcnow():
            return _to_app("token_expired")
        access.google.check_calendars(login.access_token)
        with access.database.session() as session:
            user = session.get(User, attempt.user_id, with_for_update=True)
            valid = session.execute(delete(CalendarOAuthAttempt).where(
                CalendarOAuthAttempt.state_hash == attempt.state_hash,
                CalendarOAuthAttempt.expires_at > utcnow()).returning(CalendarOAuthAttempt.state_hash)).scalar()
            if valid is None:
                return _to_app("expired")
            if user is None or (user.google_sub and user.google_sub != login.sub):
                return _to_app("different_account")
            other = session.scalar(select(User.id).where(User.google_sub == login.sub, User.id != user.id))
            if other is not None:
                return _to_app("account_conflict")
            user.google_sub = login.sub
            stored = session.get(CalendarToken, user.id)
            if stored is None:
                stored = CalendarToken(user_id=user.id)
                session.add(stored)
            stored.google_sub = login.sub
            stored.access_token_enc = access.cipher.encrypt(login.access_token)
            stored.refresh_token_enc = access.cipher.encrypt(login.refresh_token)
            stored.expires_at = login.expires_at
            stored.scopes = list(login.scopes)
    except IntegrityError:
        return _to_app("account_conflict")
    except InvalidToken:
        return _to_app("config_missing")
    except GoogleError as failure:
        return _to_app(failure.code if failure.code != "google_error" else "login_failed")
    return _to_app("connected")


def calendar_status(request, user_id):
    """매 조회마다 공급자로 확인. 장애는 토큰을 보존하되 연결 성공으로 표시하지 않는다."""
    access = request.app.state.calendar_access
    with access.database.session() as session:
        # 해제/갱신이 경합해 삭제한 토큰을 다시 쓰지 않도록 같은 사용자 잠금을 쓴다.
        session.get(User, user_id, with_for_update=True)
        stored = session.get(CalendarToken, user_id)
        if stored is None:
            return {"connected": False}
        if access.cipher is None:
            return {"connected": False, "error": "config_missing"}
        try:
            if missing_calendar_scopes(stored.scopes):
                raise CalendarDenied("stored_scope_missing")
            if stored.expires_at - ACCESS_TOKEN_MARGIN <= utcnow():
                fresh = access.google.refresh(access.cipher.decrypt(stored.refresh_token_enc))
                stored.access_token_enc = access.cipher.encrypt(fresh.token)
                stored.expires_at = fresh.expires_at
            access.google.check_calendars(access.cipher.decrypt(stored.access_token_enc))
        except (TokenExpired, InvalidToken, CalendarDenied):
            session.delete(stored)
            return {"connected": False}
        except GoogleError as failure:
            return {"connected": False, "error": failure.code}
    return {"connected": True}
