"""프레임워크를 모르는 업무 계약. 모델의 계획은 실행 권한이 아니다."""

from hashlib import sha256
import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Domain = Literal["mail", "documents", "calendar"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InputRef(Contract):
    task_id: str
    field: str


class Task(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    domain: Domain
    operation: str
    inputs: dict[str, JsonValue] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    bindings: dict[str, InputRef] = Field(default_factory=dict)
    # 서버/사용자의 확정 조건. 자동 성찰은 이 값을 수정할 수 없다.
    constraints: dict[str, JsonValue] = Field(default_factory=dict)


class Plan(Contract):
    tasks: list[Task] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def acyclic(self) -> Self:
        ids = [task.id for task in self.tasks]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate_task")
        remaining = {task.id: set(task.depends_on) for task in self.tasks}
        for task in self.tasks:
            if any(ref.task_id not in task.depends_on for ref in task.bindings.values()):
                raise ValueError("binding_requires_dependency")
            if not set(task.depends_on) <= set(ids):
                raise ValueError("unknown_dependency")
        while remaining:
            ready = {key for key, deps in remaining.items() if not deps}
            if not ready:
                raise ValueError("cyclic_plan")
            remaining = {key: deps - ready for key, deps in remaining.items() if key not in ready}
        return self


class Evidence(Contract):
    source: str
    reference: str
    version: str
    observed_at: str


class Question(Contract):
    fields: list[str] = Field(min_length=1)
    message: str


def content_hash(value: dict) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class PreparedAction(Contract):
    id: str
    task_id: str
    actor_id: int
    domain: Domain
    operation: str
    version: str
    payload: dict[str, JsonValue]

    @property
    def content_hash(self) -> str:
        return content_hash(self.model_dump(mode="json"))


class WorkResult(Contract):
    status: Literal["completed", "needs_input", "needs_review", "needs_approval", "failed"]
    data: dict[str, JsonValue] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    question: Question | None = None
    action: PreparedAction | None = None
    code: str | None = None
    editable_fields: list[str] = Field(default_factory=list)
    resume_inputs: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def required_payload(self) -> Self:
        if (self.status == "needs_input") != (self.question is not None):
            raise ValueError("question_status_mismatch")
        if (self.status == "needs_approval") != (self.action is not None):
            raise ValueError("action_status_mismatch")
        return self


class ExecutionResult(Contract):
    status: Literal["succeeded", "failed", "unknown"]
    action_id: str
    content_hash: str
    receipt: dict[str, JsonValue] = Field(default_factory=dict)
    code: str | None = None

    @model_validator(mode="after")
    def success_needs_receipt(self) -> Self:
        if self.status == "succeeded" and not self.receipt:
            raise ValueError("receipt_required")
        return self


class Approval(Contract):
    action_id: str
    content_hash: str
    decision: Literal["approve", "cancel", "modify"]
    changes: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def changes_only_on_modify(self) -> Self:
        if self.changes and self.decision != "modify":
            raise ValueError("unexpected_changes")
        return self


class Answer(Contract):
    task_id: str
    answers: dict[str, JsonValue]


class TaskResult(Contract):
    status: Literal["completed", "cancelled", "needs_review", "failed", "blocked", "unknown"]
    data: dict[str, JsonValue] = Field(default_factory=dict)
    code: str | None = None


class WorkflowError(Exception):
    """의도적으로 공개할 수 있는 오류 코드만 전달한다."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
