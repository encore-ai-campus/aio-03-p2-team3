"""일정 변경의 원래 길이와 날짜/시간 형태를 보존한다."""
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from app.graph.schemas import WorkflowError


def change_window(window: dict) -> tuple[datetime, datetime]:
    zone = ZoneInfo(window["timezone"])
    if window["all_day"]:
        return tuple(datetime.combine(date.fromisoformat(window[key]), time.min, zone) for key in ("start", "end"))
    return tuple(datetime.fromisoformat(window[key]) for key in ("start", "end"))


def moved_time(event: dict, start: str, timezone_name: str, now: datetime) -> dict:
    zone = ZoneInfo(timezone_name)
    try:
        if event["all_day"]:
            selected = date.fromisoformat(start)
            if selected < now.astimezone(zone).date():
                raise WorkflowError("past_slot")
            duration = date.fromisoformat(event["end"]) - date.fromisoformat(event["start"])
            end = selected + duration
        else:
            selected = datetime.fromisoformat(start)
            if selected.tzinfo is None:
                raise ValueError("offset_required")
            if selected <= now:
                raise WorkflowError("past_slot")
            duration = datetime.fromisoformat(event["end"]) - datetime.fromisoformat(event["start"])
            selected = selected.astimezone(zone)
            end = (selected.astimezone(timezone.utc) + duration).astimezone(zone)
        if duration.total_seconds() <= 0:
            raise ValueError("invalid_duration")
    except ValueError as error:
        raise WorkflowError("calendar_invalid_move_time") from error
    return {"start": selected.isoformat(), "end": end.isoformat(),
            "all_day": event["all_day"], "timezone": timezone_name}


def same_slot(event: dict, new_time: dict) -> bool:
    return (event["all_day"] == new_time["all_day"]
            and change_window({**event, "timezone": new_time["timezone"]}) == change_window(new_time))
