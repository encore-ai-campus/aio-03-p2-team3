"""일정 조건과 조회 스냅샷. 날짜 계산은 offset이 있는 시각으로만 한다."""

from datetime import timedelta
from typing import Self
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.graph.schemas import Contract


class Interval(Contract):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("invalid_interval")
        return self


class CalendarInput(Interval):
    timezone: str
    duration_minutes: int = Field(ge=1, le=1440, strict=True)
    calendar_ids: list[str] = Field(min_length=1, max_length=32)
    target_calendar_id: str | None = None
    participants: list[str] = Field(default_factory=list, max_length=64)
    title: str | None = Field(default=None, max_length=200)
    selected_start: AwareDatetime | None = None
    step_minutes: int = Field(default=15, ge=1, le=1440, strict=True)
    preferred_hours: list[int] | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        ZoneInfo(value)
        return value

    @field_validator("calendar_ids")
    @classmethod
    def distinct_calendars(cls, values):
        if len(set(values)) != len(values) or any(not value.strip() for value in values):
            raise ValueError("invalid_calendars")
        return values

    @field_validator("participants")
    @classmethod
    def valid_participants(cls, values):
        import re
        if any(not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value) for value in values):
            raise ValueError("invalid_participant")
        return sorted(set(values))

    @field_validator("preferred_hours")
    @classmethod
    def valid_hours(cls, values):
        if values is not None and (len(values) > 24 or any(type(value) is not int or not 0 <= value < 24 for value in values)):
            raise ValueError("invalid_hours")
        return values

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        if self.end - self.start > timedelta(days=31):
            raise ValueError("window_too_large")
        if self.selected_start is not None and not self.start <= self.selected_start < self.end:
            raise ValueError("selection_outside_window")
        if self.target_calendar_id is not None and self.target_calendar_id not in self.calendar_ids:
            raise ValueError("target_calendar_not_checked")
        return self


class BusySnapshot(Contract):
    calendars: dict[str, list[Interval]]
    version: str
    observed_at: AwareDatetime
