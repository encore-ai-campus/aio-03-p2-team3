"""로그인 화면·Google 로그인·로그아웃과 화면 경로가 함께 쓰는 로그인 확인(CONTRACT 9·10절, 계획 6절).

화면 경로는 `current_user`(로그인 안 했으면 None) 또는 `require_user`(로그인 안 했으면 /login으로)를 쓴다.
둘 다 세션의 사용자 id만 믿고(서명된 쿠키), 로그인한 사용자의 화면 요청마다 응답 뒤에
감시 갱신(`renew_watch_if_due`)을 건다. 행 하나를 id로 열 때는 `get_owned()`로 본인 것만 연다.
"""

import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.clients.gmail import GoogleError, missing_scopes
from app.db.models import GmailWatch, User
from app.services.auth import has_refresh_token, missing_login_settings, save_login, stored_scopes
from app.services.watch import register_watch, renew_watch_if_due, stop_watch
from app.web import templates

router = APIRouter()

LOGIN_NOTICES = {
    "cancelled": "Google 로그인을 취소했습니다.",
    "login_failed": "로그인을 마치지 못했습니다. 다시 시도해 주세요.",
    "scope_missing": "Gmail 읽기·보내기 권한을 모두 허용해야 쓸 수 있습니다. 다시 로그인해 권한을 모두 선택해 주세요.",
    "config_missing": "서버 설정이 끝나지 않아 지금은 로그인할 수 없습니다.",
    "logged_out": "로그아웃했습니다. 새 메일 알림도 멈췄습니다.",
}
CONNECTION_NOTICES = {
    "token_expired": "Google 연결이 만료되었거나 취소되었습니다. 다시 로그인해 주세요.",
    "watch_failed": "새 메일 알림 등록에 실패했습니다. 화면을 다시 열면 다시 시도합니다.",
    "history_expired": "Gmail 기록 조회 기간이 만료되어 로컬 수집을 멈췄습니다. 다시 로그인하면 현재 위치부터 수집합니다. 이전 메일은 자동 처리하지 않습니다.",
    "local_connect": "로컬 Gmail 연결 위치를 읽지 못했습니다. 다음 수집 주기에 다시 시도합니다.",
    "local_poll": "새 메일 조회에 실패했습니다. 다음 수집 주기에 마지막 처리 위치부터 다시 시도합니다.",
}
WATCH_LABELS = {"active": "새 메일 알림 켜짐", "error": "알림 확인 필요", "stopped": "알림 꺼짐"}
LOCAL_LABELS = {"active": "로컬 새 메일 수집 켜짐", "error": "로컬 수집 확인 필요", "stopped": "로컬 수집 꺼짐"}


def session_user(request: Request) -> User | None:
    """세션의 로그인 사용자. 감시 갱신은 걸지 않는다(로그아웃·로그인 경로용)."""
    user_id = request.session.get("user_id")
    if not isinstance(user_id, int):
        return None
    with request.app.state.database.session() as session:
        user = session.get(User, user_id)
    if user is None:
        request.session.clear()
    return user


def current_user(
    request: Request, background: BackgroundTasks, user: User | None = Depends(session_user),
) -> User | None:
    """화면 경로용 로그인 사용자. 로그인했으면 응답 뒤 감시 갱신을 건다(하루 지났거나 실패했을 때만 호출)."""
    if user is not None:
        background.add_task(renew_watch_if_due, request.app.state.google_access, user.id)
    return user


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(303, headers={"Location": "/login", "HX-Redirect": "/login"})
    return user


def connection_status(request: Request, user: User) -> dict:
    """화면에 보일 연결 상태: 감시 상태 이름, 안내 문구, 다시 로그인 필요 여부."""
    with request.app.state.database.session() as session:
        watch = session.get(GmailWatch, user.id)
        status = watch.status if watch else "stopped"
        code = (watch.last_error or "").split(":", 1)[0] if watch and status == "error" else ""
    if request.app.state.google_access.local_mode:
        owner = request.app.state.settings.local_owner_google_sub.strip()
        if not owner or user.google_sub != owner or user.last_login_at is None:
            return {"label": "로컬 수집 대기", "notice": "설정에서 본인 Google 식별자를 확인하고 .env의 소유자 설정으로 다시 시작해 주세요.", "relogin": False}
    return {
        "label": (LOCAL_LABELS if request.app.state.google_access.local_mode else WATCH_LABELS).get(status, status),
        "notice": CONNECTION_NOTICES.get(code),
        "relogin": code in {"token_expired", "history_expired"},
    }


def _to(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


@router.get("/login", include_in_schema=False)
def login_page(request: Request, notice: str | None = None, user: User | None = Depends(session_user)):
    if user is not None:
        return _to("/inbox")
    return templates.TemplateResponse(request=request, name="pages/login.html", context={
        "notice": LOGIN_NOTICES.get(notice or ""),
        "missing": missing_login_settings(request.app.state.settings),
        "local_mode": request.app.state.settings.ai_runtime == "local",
    })


@router.get("/auth/google/start", include_in_schema=False)
def google_start(request: Request, consent: bool = False, user: User | None = Depends(session_user)):
    if missing_login_settings(request.app.state.settings):
        return _to("/login?notice=config_missing")
    access = request.app.state.google_access
    # 저장된 범위에 GOOGLE_SCOPES가 다 없으면(범위를 더한 뒤 기존 사용자) 다시 동의를 받는다(CONTRACT 10절).
    if user is not None and missing_scopes(stored_scopes(access, user.id)):
        consent = True
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(64)
    request.session["oauth"] = {"state": state, "verifier": verifier, "consent": consent}
    return _to(access.google.authorization_url(state, verifier, consent=consent))


@router.get("/auth/google/callback", include_in_schema=False)
def google_callback(
    request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
):
    pending = request.session.pop("oauth", None)
    if not pending or not state or not secrets.compare_digest(state, pending["state"]):
        return _to("/login?notice=login_failed")
    if error:
        if request.app.state.google_access.local_mode:
            user = session_user(request)
            if user is not None:
                stop_watch(request.app.state.google_access, user.id)
        return _to("/login?notice=cancelled" if error == "access_denied" else "/login?notice=login_failed")
    if not code:
        return _to("/login?notice=login_failed")
    access = request.app.state.google_access
    try:
        login = access.google.exchange_code(code, pending["verifier"])
    except GoogleError:
        return _to("/login?notice=login_failed")
    if missing_scopes(login.scopes):
        return _to("/login?notice=scope_missing")
    if not login.refresh_token and not has_refresh_token(access, login.sub):
        # 갱신 토큰이 없으면 알림 처리·발송을 할 수 없다. 한 번만 동의 화면을 다시 띄워 새로 받는다.
        return _to("/login?notice=login_failed" if pending["consent"] else "/auth/google/start?consent=1")
    try:
        user_id = save_login(access, login)
    except GoogleError:
        return _to("/login?notice=config_missing")
    request.session.clear()
    request.session["user_id"] = user_id
    register_watch(access, user_id)  # 실패해도 로그인은 마치고, 받은 메일 화면이 안내한다
    return _to("/inbox")


@router.post("/logout", include_in_schema=False)
def logout(request: Request, user: User | None = Depends(session_user)):
    if user is not None:
        stop_watch(request.app.state.google_access, user.id)
    request.session.clear()
    return _to("/login?notice=logged_out")
