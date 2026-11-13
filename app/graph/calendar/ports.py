"""일정 연결의 최소 경계. 쓰기 구현은 action key/hash 원자적 중복 방지를 제공해야 한다."""

from typing import Protocol

from app.graph.calendar.schemas import BusySnapshot, CalendarInput
from app.graph.schemas import ExecutionResult, PreparedAction, WorkflowError


class CalendarPort(Protocol):
    def read_busy(self, actor_id: int, query: CalendarInput) -> BusySnapshot: ...
    def create(self, actor_id: int, action: PreparedAction) -> ExecutionResult: ...
    def lookup(self, actor_id: int, action: PreparedAction) -> ExecutionResult: ...


class UnavailableCalendar:
    """제공자가 없는 환경의 기본값. 빈 일정이나 가짜 등록 성공을 돌려주지 않는다."""

    def read_busy(self, actor_id, query):
        raise WorkflowError("calendar_not_connected")

    def create(self, actor_id, action):
        raise WorkflowError("calendar_not_connected")

    def lookup(self, actor_id, action):
        raise WorkflowError("calendar_not_connected")
