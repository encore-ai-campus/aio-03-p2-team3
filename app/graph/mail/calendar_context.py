"""수신 일정 문의에는 기본 캘린더 30일의 바쁜 구간만 사용한다."""
from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.graph.calendar.nodes import is_free, read_busy
from app.graph.calendar.schemas import CalendarInput, Interval
from app.graph.schemas import WorkflowError
from app.runlog.logger import current_event

WINDOW = timedelta(days=30)


class AvailabilityReader(Protocol):
    def read_busy(self, actor_id: int, query: CalendarInput): ...


def _alternatives(requested: Interval, window: CalendarInput, snapshot):
    duration = requested.end - requested.start
    # 요청 시각에 가까운 시간부터 비교하며, 같은 날짜에는 오전 8시~오후 10시까지만 제안한다.
    start = requested.start.astimezone(ZoneInfo(window.timezone))
    offsets = [-60, 60, -120, 120, *(day * 1440 for day in range(1, 8))]
    options = []
    for minutes in offsets:
        local = start + timedelta(minutes=minutes)
        end = (local.astimezone(UTC) + duration).astimezone(local.tzinfo)
        if local.date() == start.date() and (local.hour < 8 or end.date() != local.date() or end.hour >= 22):
            continue
        if window.start <= local < end <= window.end and is_free(Interval(start=local, end=end), snapshot):
            options.append(local.isoformat())
            if len(options) == 2:
                break
    return options


def check_mail_availability(calendar: AvailabilityReader, owner: int, proposal: dict | None,
                            *, now: datetime | None = None) -> dict:
    zone = ZoneInfo(proposal["timezone"] if proposal else "Asia/Seoul")
    start = (now or datetime.now(UTC)).astimezone(UTC)
    end = start + WINDOW
    query = CalendarInput(start=start, end=end, timezone=zone.key, duration_minutes=1, calendar_ids=["primary"])
    current_event("tool_call", tool="calendar_free_busy", detail={"days": WINDOW.days})
    try:
        snapshot = read_busy(calendar, owner, query)
    except (WorkflowError, ValidationError) as error:
        code = getattr(error, "code", "invalid_calendar_snapshot")
        current_event("tool_result", tool="calendar_free_busy", detail={"ok": False, "code": code})
        return {"status": "unavailable", "code": code, "has_start": proposal is not None,
                "duration_minutes": proposal["duration_minutes"] if proposal else None}
    current_event("tool_result", tool="calendar_free_busy", detail={"ok": True, "days": WINDOW.days})
    if not proposal:
        return {"status": "unspecified"}
    selected = datetime.fromisoformat(proposal["selected_start"])
    duration = proposal["duration_minutes"]
    finish = selected.astimezone(UTC) + timedelta(minutes=duration or 1)
    result = {"start": selected.isoformat(), "timezone": zone.key, "duration_minutes": duration}
    if selected < start or selected >= end or finish > end:
        return {**result, "status": "outside_window"}
    requested = Interval(start=selected, end=finish)
    if not is_free(requested, snapshot):
        return {**result, "status": "busy", "alternatives": _alternatives(requested, query, snapshot) if duration else []}
    return {**result, "status": "available" if duration is not None else "duration_required"}


def schedule_reply(availability: dict) -> str:
    status = availability["status"]
    if status in {"available", "busy", "duration_required"}:
        moment = datetime.fromisoformat(availability["start"])
        label = f"{moment:%m월 %d일 %H:%M} ({availability['timezone']})"
        if status == "available":
            return f"{label}부터 {availability['duration_minutes']}분간 현재 일정이 비어 있습니다. 이 시간으로 진행할지 알려주시면 확인하겠습니다."
        if status == "duration_required":
            return f"{label} 미팅에 필요한 시간을 알려주시면 가능 여부를 확인해 회신드리겠습니다."
        options = availability["alternatives"]
        if options:
            labels = ", ".join(datetime.fromisoformat(value).strftime("%m월 %d일 %H:%M") for value in options)
            return f"{label}에는 일정이 겹칩니다. 대신 {labels} ({availability['timezone']})에 시작할 수 있는데, 가능하신 시간을 알려주시겠어요?"
        return f"{label}에는 일정이 겹칩니다. 다른 희망 시간을 알려주시면 확인하겠습니다."
    if status == "unspecified" or (status == "unavailable" and availability.get("has_start") is False):
        return "조율할 일정의 날짜와 시작 시각, 필요한 시간을 알려주시면 확인하겠습니다."
    if status == "unavailable" and availability.get("has_start") and availability.get("duration_minutes") is None:
        return "미팅에 필요한 시간을 알려주시면 가능 여부를 확인해 회신드리겠습니다."
    return "요청하신 일정의 가능 여부를 추가로 확인해 회신드리겠습니다."
