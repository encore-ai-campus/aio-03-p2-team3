"""일정 노드: 조건 검사 → 전체 조회 확인 → 후보 계산 → 제안 → 재검사 → 등록."""

from datetime import datetime, timedelta, timezone
from collections.abc import Callable
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.graph.calendar.changes import change_window, moved_time, same_slot
from app.graph.calendar.ports import CalendarPort, UnavailableCalendar
from app.graph.calendar.schemas import (
    BusySnapshot, CalendarEventSelection, CalendarInput, CalendarMoveInput, Interval,
)
from app.graph.schemas import Evidence, Question, Task, WorkResult, WorkflowError

CHANGES = frozenset({"move_event", "cancel_event"})
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
    operations = frozenset({"list_events", "find_slots", "create"}) | CHANGES

    def __init__(self, port: CalendarPort | None = None, *, clock: Callable[[], datetime] | None = None):
        self.port = port if port is not None else UnavailableCalendar()
        self.clock = clock if clock is not None else lambda: datetime.now(timezone.utc)

    def prepare(self, task, context):
        if task.operation == "list_events":
            start, end = task.inputs.get("start"), task.inputs.get("end")
            if not isinstance(start, str) or not isinstance(end, str):
                return WorkResult(status="failed", code="invalid_range")
            data = self.port.list_events(context.actor_id, start, end)
            events = data["events"]
            return WorkResult(status="completed", data={
                **data, "events": events[:30], "total": len(events),
            })
        if task.operation in CHANGES:
            return self.prepare_change(task, context)
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

    def prepare_change(self, task, context):
        command = (CalendarMoveInput if task.operation == "move_event" else CalendarEventSelection).model_validate(task.inputs)
        event_id = command.event_id
        observed = any(item["id"] == event_id for result in context.results.values()
                       for item in (result.get("data") or {}).get("events", []))
        if not observed:
            return WorkResult(status="failed", code="calendar_event_lookup_required")
        event = self.port.event_for_change(context.actor_id, event_id)
        if event["recurring_series"]:
            return WorkResult(status="failed", code="calendar_select_occurrence")
        new_time = moved_time(event, command.new_start, command.timezone, self.clock()) if isinstance(command, CalendarMoveInput) else None
        if new_time is not None:
            if same_slot(event, new_time):
                return WorkResult(status="completed", data={"calendar_event": event, "outcome": "already_at_time"})
            if conflicts := self.port.competing_events(context.actor_id, event_id, *change_window(new_time)):
                return WorkResult(status="failed", code="calendar_move_conflict", data={"calendar_conflicts": conflicts[:5]})
        return WorkResult(status="needs_approval", action=context.action(
            task, {"event": event, "new_time": new_time}, version=event["etag"]))

    def recheck(self, action, context):
        if action.operation in CHANGES:
            event = self.port.event_for_change(context.actor_id, action.payload["event"]["id"])
            if event["etag"] != action.version:
                return WorkResult(status="failed", code="calendar_event_changed")
            new_time = action.payload["new_time"]
            if new_time is not None:
                moved_time(event, new_time["start"], new_time["timezone"], self.clock())
                if conflicts := self.port.competing_events(context.actor_id, event["id"], *change_window(new_time)):
                    return WorkResult(status="failed", code="calendar_move_conflict", data={"calendar_conflicts": conflicts[:5]})
            return WorkResult(status="needs_approval", action=action)
        query = CalendarInput.model_validate(action.payload["query"])
        snapshot = read_busy(self.port, context.actor_id, query)
        task = Task(id=action.task_id, domain="calendar", operation=action.operation, inputs=query.model_dump(mode="json"))
        result = prepare_event(task, context, query, snapshot, self.clock())
        evidence = [Evidence(source="calendar", reference=calendar_id, version=snapshot.version,
                             observed_at=snapshot.observed_at.isoformat()) for calendar_id in query.calendar_ids]
        return result.model_copy(update={"evidence": evidence})

    def execute(self, action, context):
        if action.operation in CHANGES:
            return self.port.change(context.actor_id, action)
        return self.port.create(context.actor_id, action)

    def lookup(self, action, context):
        if action.operation in CHANGES:
            return self.port.lookup_change(context.actor_id, action)
        return self.port.lookup(context.actor_id, action)

    def cancel(self, action, context):
        # 아직 이벤트를 만들지 않았으므로 공급자 호출이 없다.
        return None
