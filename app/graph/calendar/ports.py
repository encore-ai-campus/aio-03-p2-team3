"""일정 연결의 최소 경계. 쓰기 구현은 action key/hash 원자적 중복 방지를 제공해야 한다."""

from typing import Protocol

from app.graph.calendar.schemas import BusySnapshot, CalendarInput
from app.graph.schemas import ExecutionResult, PreparedAction, WorkflowError


class CalendarPort(Protocol):
    def list_events(self, actor_id: int, start: str, end: str) -> dict: ...
    def event_for_change(self, actor_id: int, event_id: str) -> dict: ...
    def competing_events(self, actor_id: int, event_id: str, start, end) -> list[dict]: ...
    def change(self, actor_id: int, action: PreparedAction) -> ExecutionResult: ...
    def lookup_change(self, actor_id: int, action: PreparedAction) -> ExecutionResult: ...
    def read_busy(self, actor_id: int, query: CalendarInput) -> BusySnapshot: ...
    def create(self, actor_id: int, action: PreparedAction) -> ExecutionResult: ...
    def lookup(self, actor_id: int, action: PreparedAction) -> ExecutionResult: ...


class UnavailableCalendar:
    """제공자가 없는 환경의 기본값. 빈 일정이나 가짜 등록 성공을 돌려주지 않는다."""

    def list_events(self, actor_id: int, start: str, end: str) -> dict:
        raise WorkflowError("calendar_not_connected")

    def event_for_change(self, actor_id, event_id):
        raise WorkflowError("calendar_not_connected")

    def competing_events(self, actor_id, event_id, start, end):
        raise WorkflowError("calendar_not_connected")

    def change(self, actor_id, action):
        raise WorkflowError("calendar_not_connected")

    lookup_change = change

    def read_busy(self, actor_id, query):
        raise WorkflowError("calendar_not_connected")

    def create(self, actor_id, action):
        raise WorkflowError("calendar_not_connected")

    def lookup(self, actor_id, action):
        raise WorkflowError("calendar_not_connected")
