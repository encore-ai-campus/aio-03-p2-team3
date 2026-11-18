"""계획 2절: ExistingCalendar 어댑터 — 조회 완전성·등록 멱등·unknown 복구·토큰 갱신·미연결."""
from datetime import datetime, timedelta, timezone

import pytest

from app.clients.calendar import CALENDAR_SCOPES, CalendarRejected
from app.clients.gmail import GoogleUnavailable
from app.db.models import CalendarEventReceipt, CalendarToken
from app.graph.calendar.adapters import ExistingCalendar, event_identity
from app.graph.calendar.schemas import CalendarInput, Interval
from app.graph.schemas import PreparedAction, WorkflowError
from app.services.auth import GoogleAccess, make_cipher, utcnow
from tests.fakes.google import FakeGoogle
from tests.test_gmail_connect import settings_of

KST = timezone(timedelta(hours=9))


class FakeCalendarGoogle(FakeGoogle):
    """CalendarClient 대역: free_busy·insert_event·get_event을 기록한다."""

    def __init__(self):
        super().__init__()
        self.busy = {}
        self.errors = {}
        self.events = {}
        self.insert_error = None
        self.created_but_unconfirmed = False  # 서버는 만들었지만 응답을 받지 못한 상황

    def free_busy(self, access_token, calendar_ids, start, end):
        self.calls.append(("free_busy", tuple(calendar_ids)))
        return {calendar_id: {"busy": list(self.busy.get(calendar_id, [])),
                              "errors": list(self.errors.get(calendar_id, []))}
                for calendar_id in calendar_ids}

    def insert_event(self, access_token, calendar_id, *, summary, start, end, timezone,
                     attendees=(), event_id=None):
        self.calls.append(("insert", calendar_id, summary, event_id))
        if self.insert_error is not None:
            if self.created_but_unconfirmed:
                self.events[(calendar_id, event_id)] = "confirmed"
            raise self.insert_error
        self.events[(calendar_id, event_id)] = "confirmed"
        return event_id

    def get_event(self, access_token, calendar_id, event_id):
        self.calls.append(("get_event", calendar_id, event_id))
        status = self.events.get((calendar_id, event_id))
        return None if status is None else {"id": event_id, "status": status}


def query_of(*calendar_ids, start=None, duration=120):
    return CalendarInput(start=start or datetime(2026, 11, 24, 9, tzinfo=KST),
                         end=datetime(2026, 11, 24, 18, tzinfo=KST),
                         timezone="Asia/Seoul", duration_minutes=duration, calendar_ids=list(calendar_ids))


def action_of(query, slot=None):
    slot = slot or Interval(start=datetime(2026, 11, 24, 13, tzinfo=KST),
                            end=datetime(2026, 11, 24, 15, tzinfo=KST))
    return PreparedAction(id="action" + "0" * 26, task_id="task-1", actor_id=1, domain="calendar",
                          operation="create", version="v1",
                          payload={"query": query.model_dump(mode="json"), "slot": slot.model_dump(mode="json")})


@pytest.fixture
def harness(database):
    google = FakeCalendarGoogle()
    settings = settings_of(str(database.engine.url))
    access = GoogleAccess(database, google, make_cipher(settings), "")
    with database.session() as session:
        session.add(CalendarToken(user_id=1, google_sub="fake-sub-1",
                                  refresh_token_enc=access.cipher.encrypt("refresh-1"),
                                  access_token_enc=access.cipher.encrypt("access-1"),
                                  expires_at=utcnow() + timedelta(hours=1),
                                  scopes=list(CALENDAR_SCOPES)))
    return ExistingCalendar(access), google, database


def test_read_busy_keeps_every_requested_calendar_and_fails_on_calendar_errors(harness):
    adapter, google, _ = harness
    google.busy = {"primary": [(datetime(2026, 11, 24, 9, tzinfo=KST), datetime(2026, 11, 24, 10, tzinfo=KST))]}
    snapshot = adapter.read_busy(1, query_of("primary", "secondary"))
    # 빈 캘린더도 키로 남아 노드의 완전성 검사 기준과 일치한다.
    assert set(snapshot.calendars) == {"primary", "secondary"}
    assert len(snapshot.calendars["primary"]) == 1 and snapshot.calendars["secondary"] == []

    google.errors = {"secondary": ["notFound"]}
    with pytest.raises(WorkflowError) as failure:
        adapter.read_busy(1, query_of("primary", "secondary"))
    assert failure.value.code == "calendar_unavailable"


def test_create_is_idempotent_and_rejects_a_different_hash_for_the_same_action(harness):
    adapter, google, database = harness
    action = action_of(query_of("primary"))
    first = adapter.create(1, action)
    assert first.status == "succeeded" and first.receipt["event_id"] == event_identity(action)
    assert len(google.called("insert")) == 1

    again = adapter.create(1, action)  # 같은 승인의 재실행은 저장 영수증을 돌려준다.
    assert again.status == "succeeded" and again.receipt == first.receipt
    assert len(google.called("insert")) == 1
    with database.session() as session:
        assert session.get(CalendarEventReceipt, action.id).event_id == event_identity(action)

    modified = action.model_copy(update={"payload": {**action.payload, "slot": {
        "start": "2026-11-24T14:00:00+09:00", "end": "2026-11-24T16:00:00+09:00"}}})
    assert adapter.create(1, modified).code == "idempotency_conflict"
    assert len(google.called("insert")) == 1


def test_timeout_keeps_receipt_empty_and_lookup_recovers_the_created_event(harness):
    adapter, google, database = harness
    action = action_of(query_of("primary"))
    google.insert_error = GoogleUnavailable("calendar_transport")
    google.created_but_unconfirmed = True

    unknown = adapter.create(1, action)
    assert unknown.status == "unknown" and unknown.code == "calendar_unconfirmed"
    with database.session() as session:
        assert session.get(CalendarEventReceipt, action.id) is None

    recovered = adapter.lookup(1, action)  # 결정적 이벤트 ID로 등록을 확인해 복구한다.
    assert recovered.status == "succeeded" and recovered.receipt["event_id"] == event_identity(action)
    with database.session() as session:
        assert session.get(CalendarEventReceipt, action.id).content_hash == action.content_hash
    assert not google.called("refresh")  # 저장 토큰이 아직 유효해 조회에는 갱신이 필요 없다.


def test_rejected_create_fails_definitively_and_missing_connection_is_reported(harness, database):
    adapter, google, _ = harness
    google.insert_error = CalendarRejected("일정 등록이 거부됐다")
    rejected = adapter.create(1, action_of(query_of("primary")))
    assert rejected.status == "failed" and rejected.code == "calendar_rejected"

    with database.session() as session:  # 연결이 없으면 조회·등록 모두 미연결로 안내한다.
        session.delete(session.get(CalendarToken, 1))
    assert adapter.create(1, action_of(query_of("primary"))).code == "calendar_not_connected"
    with pytest.raises(WorkflowError) as read:
        adapter.read_busy(1, query_of("primary"))
    assert read.value.code == "calendar_not_connected"


def test_expired_access_token_is_refreshed_and_persisted(harness, database):
    adapter, google, _ = harness
    with database.session() as session:
        stored = session.get(CalendarToken, 1)
        stored.expires_at = utcnow() - timedelta(minutes=1)  # 만료: 갱신 경로를 지난다.
    result = adapter.create(1, action_of(query_of("primary")))
    assert result.status == "succeeded" and len(google.called("refresh")) == 1
    with database.session() as session:
        assert session.get(CalendarToken, 1).expires_at > utcnow()
