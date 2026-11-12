"""Gmail 연결 API — 앱 로그인(legacy) 흐름과 분리된 Bearer 전용 경로(CONTRACT 9.1절, 계획 7절).

- `POST /api/gmail/connect`: 연결 시작. state·PKCE 검증값·연결할 내부 사용자·기대 Google
  subject를 서명된 세션 쿠키에 잠깐 보관하고 Google 동의 화면 주소를 JSON으로 돌려준다.
- `GET /auth/google/callback`(완성은 `complete_callback`): 대기 값에 내부 사용자가 있으면 이
  흐름으로 완성해 React 앱(`/app/settings?gmail=…`)으로 안내한다. legacy 로그인은 그대로다.
- `POST /api/gmail/disconnect`: Google 토큰까지 폐기하는 연결 해제. `google_sub`는 남겨
  같은 계정만 다시 연결할 수 있게 한다.
- `POST /api/gmail/logout`: 앱 로그아웃 때 프론트가 부르는 감시 중지(토큰은 보존).
- 연결 상태는 `GET /api/me`의 `gmail` 객체가 담당하고, 그 요청 뒤 감시 갱신을 건다.

계정 규칙(CONTRACT 9.1): 같은 이메일이라고 자동 병합하지 않는다. Supabase Auth가 확인한
공급자 subject(`TokenVerifier.provider_google_subject`, 서버 비밀 키로만 읽는다)와 Google
재인증 결과의 subject가 일치할 때만 기존 정수 사용자 ID를 보존해 연결한다. 양쪽에 이미
자료가 있으면 외래 키가 삭제를 막아 충돌로 거부한다(자동 합병 없음).
"""

import secrets
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.supabase import bearer_user_id
from app.clients.gmail import GoogleError, TokenExpired, missing_scopes
from app.db.models import GmailWatch, GoogleToken, User
from app.services.auth import (
    delete_login_tokens, google_refresh_token, has_refresh_token, missing_login_settings,
    store_login, stored_scopes, utcnow,
)
from app.services.watch import register_watch, stop_watch

router = APIRouter(prefix="/api/gmail", tags=["gmail-connection"])

# 연결 시작 state 유효 기간(초). 짧게만 살고, callback에서 한 번 쓰면 사라진다.
STATE_TTL_SECONDS = 600


class GmailConnectionError(Exception):
    """Gmail 연결 API 실패. `app/main.py`가 `{"error": …}` JSON으로 바꾼다. `code`는 callback
    안내(`/app/settings?gmail=<code>`)에도 쓴다."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def gmail_status(request: Request, user_id: int) -> dict:
    """`GET /api/me`와 이 라우터가 같이 쓰는 Gmail 연결 상태."""
    with request.app.state.database.session() as session:
        token = session.get(GoogleToken, user_id)
        watch = session.get(GmailWatch, user_id)
    return {
        "connected": bool(token and token.refresh_token_enc),
        "watch": watch.status if watch else "stopped",
    }


@router.post("/connect")
def connect(request: Request, user_id: int = Depends(bearer_user_id)):
    """연결 시작. 돌려준 주소로 이동하면 Google 동의 화면이 열리고 callback이 이 흐름을 마친다."""
    settings = request.app.state.settings
    missing = missing_login_settings(settings)
    if not settings.supabase_secret_key:
        missing.append("SUPABASE_SECRET_KEY")
    if missing:
        raise GmailConnectionError(
            503, "config_missing",
            f"서버 설정이 끝나지 않아 Gmail 연결을 시작할 수 없습니다({', '.join(missing)}).")
    # 대기 값에는 계정 증명에 쓸 Supabase 공급자 subject를 미리 담아 둔다. callback 요청에는
    # Bearer 토큰이 없어 callback 안에서는 이 값을 구할 수 없다.
    _, _, token = request.headers.get("authorization", "").partition(" ")
    verified = request.app.state.supabase_auth.verify(token.strip())
    expected = request.app.state.supabase_auth.provider_google_subject(verified.sub)
    access = request.app.state.google_access
    # 저장된 범위에 GOOGLE_SCOPES가 다 없으면(범위를 더한 뒤 기존 사용자) 다시 동의를 받는다.
    with request.app.state.database.session() as session:
        has_stored_token = session.get(GoogleToken, user_id) is not None
    consent = has_stored_token and bool(missing_scopes(stored_scopes(access, user_id)))
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(64)
    request.session["oauth"] = {
        "state": state, "verifier": verifier, "consent": consent,
        "user_id": user_id, "google_sub": expected, "at": time.time(),
    }
    return {"authorization_url": access.google.authorization_url(state, verifier, consent=consent)}


@router.post("/disconnect")
def disconnect(request: Request, user_id: int = Depends(bearer_user_id)):
    """연결 해제: Google에서 토큰을 폐기하고 감시를 멈춘 뒤 저장된 토큰을 지운다."""
    access = request.app.state.google_access
    refresh = google_refresh_token(access, user_id)
    if refresh is not None:
        try:
            access.google.revoke(refresh)
        except TokenExpired:
            pass  # 이미 폐기됐거나 취소됐으면 로컬 정리만 계속한다
        except GoogleError as error:
            raise GmailConnectionError(503, error.code,
                                       "Google 토큰 폐기에 실패했습니다. 잠시 후 다시 시도해 주세요.") from error
    stop_watch(access, user_id)
    delete_login_tokens(access, user_id)
    return gmail_status(request, user_id)


@router.post("/logout")
def logout(request: Request, user_id: int = Depends(bearer_user_id)):
    """앱 로그아웃 보조: 감시만 멈춘다. Google 토큰은 보존해 재연결 때 다시 켠다."""
    stop_watch(request.app.state.google_access, user_id)
    return gmail_status(request, user_id)


def complete_callback(request: Request, pending: dict, state: str | None,
                      code: str | None, error: str | None) -> RedirectResponse:
    """`GET /auth/google/callback`의 Gmail 연결 분기. 결과는 React 앱으로 안내한다."""
    if not state or not secrets.compare_digest(state, pending["state"]):
        return _to_app("login_failed")
    if time.time() - pending.get("at", 0) > STATE_TTL_SECONDS:
        return _to_app("expired")
    if error:
        return _to_app("cancelled" if error == "access_denied" else "login_failed")
    if not code:
        return _to_app("login_failed")
    access = request.app.state.google_access
    try:
        login = access.google.exchange_code(code, pending["verifier"])
    except GoogleError:
        return _to_app("login_failed")
    if missing_scopes(login.scopes):
        return _to_app("scope_missing")
    if not login.refresh_token and not has_refresh_token(access, login.sub):
        # 갱신 토큰이 없으면 알림 처리·발송을 할 수 없다. 한 번만 동의 화면을 다시 띄워 새로 받는다.
        if pending.get("consent"):
            return _to_app("login_failed")
        return _restart_with_consent(request, access, pending)
    try:
        user_id = _connect_user(access, pending, login)
    except GmailConnectionError as rejected:
        return _to_app(rejected.code)
    except GoogleError:
        return _to_app("config_missing")
    register_watch(access, user_id)  # 실패해도 연결은 마치고, 상태 화면이 안내한다
    return _to_app("connected")


def _restart_with_consent(request: Request, access, pending: dict) -> RedirectResponse:
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(64)
    request.session["oauth"] = {
        **pending, "state": state, "verifier": verifier, "consent": True, "at": time.time(),
    }
    return RedirectResponse(access.google.authorization_url(state, verifier, consent=True),
                            status_code=303)


def _connect_user(access, pending: dict, login) -> int:
    """콜백 결과를 저장할 내부 사용자 id를 정한다. 조건이 맞으면 기존 정수 ID를 보존해 연결한다."""
    expected = pending.get("google_sub")
    current_id = pending["user_id"]
    if expected and login.sub != expected:
        raise GmailConnectionError(
            409, "different_account",
            "앱 로그인에 쓴 Google 계정과 다른 계정이 돌아왔습니다. 같은 계정으로 다시 시도해 주세요.")
    with access.database.session() as session:
        current = session.get(User, current_id)
        if current is None:
            raise GmailConnectionError(
                409, "account_conflict", "연결을 시작한 사용자를 찾을 수 없습니다. 다시 시도해 주세요.")
        if current.google_sub and current.google_sub != login.sub:
            raise GmailConnectionError(
                409, "different_account",
                "이미 다른 Google 계정에 연결되어 있습니다. 연결을 해제한 뒤 다시 시도해 주세요.")
        existing = session.scalar(
            select(User).where(User.google_sub == login.sub, User.id != current_id))
        if existing is None:
            store_login(session, access, current, login, utcnow())
            return current_id
        # 같은 Google 계정을 쓰는 다른 행이 있다.
        if existing.supabase_uid is not None or not expected:
            raise GmailConnectionError(
                409, "account_conflict",
                "이 Google 계정은 이미 다른 로그인에 연결되어 있습니다. 관리자에게 문의해 주세요.")
        # 재인증으로 같은 계정임을 확인했다. 기존 정수 ID(자료)를 보존해 이 로그인을 연결한다.
        supabase_uid = current.supabase_uid
        try:
            current.supabase_uid = None
            for husk in (session.get(GoogleToken, current_id), session.get(GmailWatch, current_id)):
                if husk is not None:  # 아직 연결된 적 없는 사용자의 빈 껍데기 행뿐이다.
                    session.delete(husk)
            session.flush()
            existing.supabase_uid = supabase_uid
            store_login(session, access, existing, login, utcnow())
            session.delete(current)  # 양쪽에 자료가 있으면 외래 키가 삭제를 막는다(자동 합병 금지)
            session.flush()
        except IntegrityError as error:
            raise GmailConnectionError(
                409, "account_conflict",
                "기존 계정과 새 계정 양쪽에 이미 자료가 있어 자동으로 합치지 않습니다. "
                "기존 자료를 쓰려면 기존 계정으로 다시 시도해 주세요.") from error
        return existing.id


def _to_app(notice: str) -> RedirectResponse:
    return RedirectResponse(f"/app/settings?gmail={notice}", status_code=303)
