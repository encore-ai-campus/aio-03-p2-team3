"""주 캘린더 목록 조회와 공통 Calendar 접근 토큰 갱신."""
from datetime import datetime, timedelta

from cryptography.fernet import InvalidToken

from app.clients.calendar import CalendarDenied, missing_calendar_scopes
from app.clients.gmail import GoogleError, TokenExpired
from app.db.models import CalendarToken, User
from app.services.auth import ACCESS_TOKEN_MARGIN, GoogleAccess, utcnow

EVENTS_WINDOW_MAX_DAYS = 62


class CalendarEventsError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def calendar_access_token(session, access, stored: CalendarToken) -> str:
    """CalendarToken의 접근 토큰. 만료가 가까우면 갱신해 같은 행에 저장한다.
    상태 조회와 그래프 어댑터가 같은 갱신 로직을 쓴다(계획 2절)."""
    if stored.expires_at - ACCESS_TOKEN_MARGIN <= utcnow():
        fresh = access.google.refresh(access.cipher.decrypt(stored.refresh_token_enc))
        stored.access_token_enc = access.cipher.encrypt(fresh.token)
        stored.expires_at = fresh.expires_at
    return access.cipher.decrypt(stored.access_token_enc)


def _events_window(start: str, end: str) -> tuple[datetime, datetime]:
    """조회 범위 검증. offset을 포함한 ISO 시각만 받는다(시간대는 화면이 정한다)."""
    try:
        window_start, window_end = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except ValueError:
        window_start = window_end = None
    if (window_start is None or window_start.tzinfo is None or window_end is None
            or window_end.tzinfo is None or window_end <= window_start):
        raise CalendarEventsError(400, "invalid_range",
                                   "start·end는 시간대(offset)를 포함한 ISO 시각이어야 하고 end가 start보다 뒤여야 합니다.")
    if window_end - window_start > timedelta(days=EVENTS_WINDOW_MAX_DAYS):
        raise CalendarEventsError(400, "range_too_large",
                                   f"조회 범위는 {EVENTS_WINDOW_MAX_DAYS}일 이하여야 합니다.")
    return window_start, window_end


def _events_token(access: GoogleAccess, user_id: int):
    """조회용 접근 토큰과 실패 안내. 갱신·실패 분류는 연결 상태 조회와 같은 체계를 쓴다."""
    with access.database.session() as session:
        # 해제/갱신 경합에서 삭제된 토큰을 다시 쓰지 않도록 같은 사용자 잠금을 쓴다.
        session.get(User, user_id, with_for_update=True)
        stored = session.get(CalendarToken, user_id)
        if stored is None:
            return None, (409, "calendar_not_connected",
                          "Google 캘린더가 연결되지 않았습니다. 설정의 연동하기에서 연결해 주세요.")
        if access.cipher is None:
            return None, (503, "config_missing", "서버의 Calendar 연결 설정이 끝나지 않았습니다.")
        try:
            if missing_calendar_scopes(stored.scopes):
                raise CalendarDenied("stored_scope_missing")
            return calendar_access_token(session, access, stored), None
        except (TokenExpired, InvalidToken, CalendarDenied):
            session.delete(stored)
            return None, (409, "calendar_not_connected",
                          "구글 캘린더 연결이 만료됐습니다. 설정의 연동하기에서 다시 연결해 주세요.")
        except GoogleError as failure:
            return None, (503, failure.code,
                          "구글 캘린더 연결 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.")


def list_primary_events(access: GoogleAccess, user_id: int, start: str, end: str) -> dict:
    window_start, window_end = _events_window(start, end)
    token, failure = _events_token(access, user_id)
    if failure:
        raise CalendarEventsError(*failure)
    try:
        found = access.google.list_events(token, "primary", time_min=window_start, time_max=window_end)
    except GoogleError as error:
        raise CalendarEventsError(502, error.code,
                                  "구글 캘린더 일정을 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.") from error
    return {"calendar_id": "primary", "start": start, "end": end, "events": found}
