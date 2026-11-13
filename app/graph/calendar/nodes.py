"""일정 노드: 조건 검사 → 전체 조회 확인 → 후보 계산 → 제안 → 재검사 → 등록."""

from datetime import datetime, timedelta, timezone
from collections.abc import Callable
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.graph.calendar.ports import CalendarPort, UnavailableCalendar
from app.graph.calendar.schemas import BusySnapshot, CalendarInput, Interval
from app.graph.schemas import Evidence, Question, Task, WorkResult, WorkflowError

REQUIRED = ("start", "end", "timezone", "duration_minutes", "calendar_ids")


def check_constraints(task: Task):
    missing = [key for key in REQUIRED if task.inputs.get(key) in (None, "", [])]
    if missing:
        return WorkResult(status="needs_input", question=Question(fields=missing, message="일정 조건을 알려 주세요."))
    try:
        return CalendarInput.model_validate(task.inputs)
    except (ValidationError, KeyError, ValueError):
        return WorkResult(status="failed", code="invalid_calendar_constraints")


def read_busy(port: CalendarPort, actor_id: int, query: CalendarInput) -> BusySnapshot:
    snapshot = BusySnapshot.model_validate(port.read_busy(actor_id, query))
    if set(snapshot.calendars) != set(query.calendar_ids):
        raise WorkflowError("incomplete_calendar_lookup")
    return snapshot


def is_free(slot: Interval, snapshot: BusySnapshot) -> bool:
    return all(slot.end <= busy.start or slot.start >= busy.end
               for intervals in snapshot.calendars.values() for busy in intervals)


def compute_slots(query: CalendarInput, snapshot: BusySnapshot, preferences: dict) -> list[Interval]:
    start, end = query.start.astimezone(timezone.utc), query.end.astimezone(timezone.utc)
    duration, step = timedelta(minutes=query.duration_minutes), timedelta(minutes=query.step_minutes)
    slots = []
    while start + duration <= end:
        slot = Interval(start=start, end=start + duration)
        if is_free(slot, snapshot):
            slots.append(slot)
        start += step
    hours = query.preferred_hours
    if hours is None:
        hours = preferences.get("calendar_preferred_hours", [])
    if not isinstance(hours, list) or any(type(hour) is not int or not 0 <= hour < 24 for hour in hours):
        hours = []
    zone = ZoneInfo(query.timezone)
    slots.sort(key=lambda slot: (slot.start.astimezone(zone).hour not in hours, slot.start))
    return slots[:3]


def prepare_event(task, context, query, snapshot, now):
    if query.selected_start <= now:
        return WorkResult(status="needs_input", code="past_slot", question=Question(
            fields=["selected_start", "start", "end"], message="등록할 미래 시간을 선택해 주세요."))
    slot = Interval(start=query.selected_start, end=query.selected_start + timedelta(minutes=query.duration_minutes))
    if slot.end > query.end or not is_free(slot, snapshot):
        slots = compute_slots(query, snapshot, context.memory.get("preferences", {}))
        return WorkResult(status="needs_input", code="slot_unavailable", data={"slots": [s.model_dump(mode="json") for s in slots]},
                          question=Question(fields=["selected_start", "start", "end"], message="다른 시간이나 조회 범위를 선택해 주세요."))
    payload = {"query": query.model_dump(mode="json"), "slot": slot.model_dump(mode="json")}
    action = context.action(task, payload, version=snapshot.version)
    return WorkResult(status="needs_approval", action=action)


class CalendarNodes:
    operations = frozenset({"find_slots", "create"})

    def __init__(self, port: CalendarPort | None = None, *, clock: Callable[[], datetime] | None = None):
        self.port = port if port is not None else UnavailableCalendar()
        self.clock = clock if clock is not None else lambda: datetime.now(timezone.utc)

    def prepare(self, task, context):
        query = check_constraints(task)
        if isinstance(query, WorkResult):
            return query
        snapshot = read_busy(self.port, context.actor_id, query)
        evidence = [Evidence(source="calendar", reference=calendar_id, version=snapshot.version,
                             observed_at=snapshot.observed_at.isoformat()) for calendar_id in query.calendar_ids]
        slots = [slot.model_dump(mode="json") for slot in compute_slots(query, snapshot, context.memory.get("preferences", {}))]
        if task.operation == "find_slots":
            return WorkResult(status="completed", data={"slots": slots, "outcome": "available" if slots else "no_slots"}, evidence=evidence)
        if query.target_calendar_id is None and len(query.calendar_ids) == 1:
            query = query.model_copy(update={"target_calendar_id": query.calendar_ids[0]})
        if not query.title or query.selected_start is None or query.target_calendar_id is None:
            missing = (["title"] if not query.title else []) + (["selected_start"] if query.selected_start is None else [])
            if query.target_calendar_id is None:
                missing.append("target_calendar_id")
            return WorkResult(status="needs_input", data={"slots": slots}, evidence=evidence,
                              question=Question(fields=missing + (["start", "end"] if not slots else []),
                                                message="등록할 제목과 시간을 선택해 주세요."))
        return prepare_event(task, context, query, snapshot, self.clock()).model_copy(update={"evidence": evidence})

    def recheck(self, action, context):
        query = CalendarInput.model_validate(action.payload["query"])
        snapshot = read_busy(self.port, context.actor_id, query)
        task = Task(id=action.task_id, domain="calendar", operation=action.operation, inputs=query.model_dump(mode="json"))
        result = prepare_event(task, context, query, snapshot, self.clock())
        evidence = [Evidence(source="calendar", reference=calendar_id, version=snapshot.version,
                             observed_at=snapshot.observed_at.isoformat()) for calendar_id in query.calendar_ids]
        return result.model_copy(update={"evidence": evidence})

    def execute(self, action, context):
        return self.port.create(context.actor_id, action)

    def lookup(self, action, context):
        return self.port.lookup(context.actor_id, action)

    def cancel(self, action, context):
        # 아직 이벤트를 만들지 않았으므로 공급자 호출이 없다.
        return None
