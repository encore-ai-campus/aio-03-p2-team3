"""CalendarPort의 Google 구현. 토큰 갱신·영수증 SQL·Google 호출을 어댑터가 소유한다(계획 2절).

계약(`CalendarPort`·`CalendarInput`·`BusySnapshot`)은 바꾸지 않고 `CalendarClient`의 세 호출을
연결한다. 등록은 결정적 이벤트 ID(action content_hash)로 멱등을 지키므로 타임아웃 뒤 조회가
같은 이벤트를 확인해 영수증을 복구할 수 있다(Gmail 발송의 failed_unknown 계약과 같다).
"""

from cryptography.fernet import InvalidToken
from sqlalchemy.exc import IntegrityError

from app.auth.calendar import calendar_access_token
from app.clients.calendar import CalendarRejected
from app.clients.gmail import GoogleError, TokenExpired
from app.db.models import CalendarEventReceipt, CalendarToken
from app.graph.calendar.schemas import BusySnapshot, CalendarInput, Interval
from app.graph.schemas import ExecutionResult, PreparedAction, WorkflowError, content_hash
from app.services.auth import GoogleAccess, utcnow
from app.services.locks import user_lock

UNCONFIRMED = "calendar_unconfirmed"


class ConnectionDropped(Exception):
    """연결이 끊겼다(토큰 만료·취소·읽기 실패). 갱신 토큰 무효는 `calendar_status` 정책과
    같이 행을 지우고 재연결로 안내한다."""


class ProviderDown(Exception):
    """Google 통신/서비스 오류. 등록 결과를 확인할 수 없다."""


def event_identity(action: PreparedAction) -> str:
    """같은 승인의 재실행·조회 복구에 쓰는 결정적 이벤트 ID(16진수 앞자리, base32hex 호환)."""
    return "tm" + action.content_hash[:30]


class ExistingCalendar:
    """설정 화면에서 연결한 CalendarToken으로 실제 Google Calendar를 읽고 등록한다."""

    def __init__(self, access: GoogleAccess):
        self.access = access

    @property
    def database(self):
        return self.access.database

    def read_busy(self, actor_id: int, query: CalendarInput) -> BusySnapshot:
        """요청한 캘린더 전부를 담는다(빈 캘린더도). 조회 오류 캘린더가 있으면 실패한다."""
        with self.database.session() as session:
            stored = self._token(session, actor_id)
            if stored is None:
                raise WorkflowError("calendar_not_connected")
            token = self._access_token(session, stored)
            try:
                raw = self.access.google.free_busy(token, query.calendar_ids, query.start, query.end)
            except GoogleError as error:
                raise WorkflowError("calendar_unavailable") from error
            intervals, version = {}, {}
            for calendar_id in query.calendar_ids:
                entry = raw.get(calendar_id) or {}
                if entry.get("errors"):
                    raise WorkflowError("calendar_unavailable")
                intervals[calendar_id] = [Interval(start=start, end=end) for start, end in entry.get("busy", [])]
                version[calendar_id] = [[start.isoformat(), end.isoformat()] for start, end in entry.get("busy", [])]
        return BusySnapshot(calendars=intervals, version=content_hash(version), observed_at=utcnow())

    def create(self, actor_id: int, action: PreparedAction) -> ExecutionResult:
        query = CalendarInput.model_validate(action.payload["query"])
        calendar_id = self._target(query)
        if calendar_id is None:
            return self._result(action, "failed", "calendar_target_required")
        with user_lock(self.database, actor_id), self.database.session() as session:
            stored_receipt = session.get(CalendarEventReceipt, action.id)
            if stored_receipt is not None:
                return self._receipt(action, stored_receipt)
            stored = self._token(session, actor_id)
            if stored is None:
                return self._result(action, "failed", "calendar_not_connected")
            try:
                token = self._access_token(session, stored)
            except ConnectionDropped:
                return self._result(action, "failed", "calendar_not_connected")
            except ProviderDown:
                return self._result(action, "unknown", UNCONFIRMED)
            slot = Interval.model_validate(action.payload["slot"])
            try:
                event_id = self.access.google.insert_event(token, calendar_id, summary=query.title or "",
                    start=slot.start, end=slot.end, timezone=query.timezone, attendees=query.participants,
                    event_id=event_identity(action))
            except CalendarRejected:
                return self._result(action, "failed", "calendar_rejected")
            except GoogleError:
                return self._result(action, "unknown", UNCONFIRMED)
            try:
                session.add(CalendarEventReceipt(action_id=action.id, user_id=actor_id, event_id=event_id,
                                                 calendar_id=calendar_id, content_hash=action.content_hash))
                session.flush()
            except IntegrityError:
                # 같은 action의 동시 실행이 먼저 영수증을 저장했다. 그 결과를 돌려준다.
                session.rollback()
                return self._receipt(action, session.get(CalendarEventReceipt, action.id))
            return self._payload(action, event_id, calendar_id)

    def lookup(self, actor_id: int, action: PreparedAction) -> ExecutionResult:
        """저장 영수증이 없으면 결정적 이벤트 ID로 등록 여부를 확인해 타임아웃 뒤 복구한다."""
        query = CalendarInput.model_validate(action.payload["query"])
        calendar_id = self._target(query)
        with user_lock(self.database, actor_id), self.database.session() as session:
            stored_receipt = session.get(CalendarEventReceipt, action.id)
            if stored_receipt is not None:
                return self._receipt(action, stored_receipt)
            stored = self._token(session, actor_id)
            if calendar_id is None or stored is None:
                return self._result(action, "unknown", UNCONFIRMED)
            try:
                token = self._access_token(session, stored)
            except Exception:
                return self._result(action, "unknown", UNCONFIRMED)
            try:
                event = self.access.google.get_event(token, calendar_id, event_identity(action))
            except GoogleError:
                return self._result(action, "unknown", UNCONFIRMED)
            if event is None or event.get("status") == "cancelled":
                return self._result(action, "unknown", UNCONFIRMED)
            session.add(CalendarEventReceipt(action_id=action.id, user_id=actor_id, event_id=event["id"],
                                             calendar_id=calendar_id, content_hash=action.content_hash))
            return self._payload(action, event["id"], calendar_id)

    @staticmethod
    def _token(session, actor_id):
        return session.get(CalendarToken, actor_id)

    def _access_token(self, session, stored: CalendarToken) -> str:
        """만료가 가까우면 갱신한다(`calendar_status`와 같은 갱신 로직·삭제 정책)."""
        try:
            return calendar_access_token(session, self.access, stored)
        except (TokenExpired, InvalidToken) as error:
            session.delete(stored)
            raise ConnectionDropped() from error
        except GoogleError as error:
            raise ProviderDown() from error

    @staticmethod
    def _target(query: CalendarInput) -> str | None:
        return query.target_calendar_id or (query.calendar_ids[0] if len(query.calendar_ids) == 1 else None)

    @staticmethod
    def _result(action: PreparedAction, status: str, code: str) -> ExecutionResult:
        return ExecutionResult(status=status, action_id=action.id, content_hash=action.content_hash, code=code)

    @staticmethod
    def _receipt(action: PreparedAction, stored: CalendarEventReceipt) -> ExecutionResult:
        if stored.content_hash != action.content_hash:
            return ExistingCalendar._result(action, "failed", "idempotency_conflict")
        return ExistingCalendar._payload(action, stored.event_id, stored.calendar_id)

    @staticmethod
    def _payload(action: PreparedAction, event_id: str, calendar_id: str) -> ExecutionResult:
        return ExecutionResult(status="succeeded", action_id=action.id, content_hash=action.content_hash,
                               receipt={"event_id": event_id, "calendar_id": calendar_id})
