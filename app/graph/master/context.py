"""실행 문맥과 외부 경계. 체크포인트에는 서비스 객체나 승인 권한을 넣지 않는다."""

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Callable, Protocol
from uuid import NAMESPACE_URL, uuid5

from app.graph.schemas import ExecutionResult, Plan, PreparedAction, Task, WorkResult, content_hash


@dataclass(frozen=True)
class WorkContext:
    actor_id: int
    thread_id: str
    round: int
    memory: dict
    results: dict

    def action(self, task: Task, payload: dict, *, version: str) -> PreparedAction:
        return PreparedAction(
            id=uuid5(NAMESPACE_URL, f"{self.thread_id}/{task.id}/{self.round}/{version}/{content_hash(payload)}").hex,
            actor_id=self.actor_id, task_id=task.id, domain=task.domain,
            operation=task.operation, version=version, payload=payload,
        )


class DomainHandler(Protocol):
    operations: frozenset[str]

    def prepare(self, task: Task, context: WorkContext) -> WorkResult: ...
    def recheck(self, action: PreparedAction, context: WorkContext) -> WorkResult: ...
    def execute(self, action: PreparedAction, context: WorkContext) -> ExecutionResult: ...
    def lookup(self, action: PreparedAction, context: WorkContext) -> ExecutionResult: ...
    def cancel(self, action: PreparedAction, context: WorkContext) -> None: ...


@dataclass(frozen=True)
class Dependencies:
    handlers: dict[str, DomainHandler]
    load_context: Callable[[int, str], dict] = lambda actor, thread: {}
    planner: Callable[[str, WorkContext], Plan] | None = None
    repair: Callable[[Task, WorkResult, WorkContext], dict] | None = None
    repair_limit: int = 3


@dataclass
class _ExecutionGrant:
    thread_id: str
    action_id: str
    content_hash: str
    consumed: bool = field(default=False)

    def consume(self, thread_id: str, action: PreparedAction) -> bool:
        if self.consumed or (self.thread_id, self.action_id, self.content_hash) != (
            thread_id, action.id, action.content_hash,
        ):
            return False
        self.consumed = True
        return True


execution_grant: ContextVar[_ExecutionGrant | None] = ContextVar("graph_execution_grant", default=None)
