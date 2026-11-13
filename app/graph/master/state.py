"""범용 마스터 상태. Gmail 경계의 AgentState와 별도로 관리한다."""

from typing import TypedDict


class WorkflowState(TypedDict):
    actor_id: int
    thread_id: str
    request: str
    memory: dict
    tasks: list[dict]
    results: dict[str, dict]
    current: str | None
    work: dict | None
    rounds: dict[str, int]
    repairs: dict[str, int]
    attempts: dict[str, str]
    actions: dict[str, dict]
    evidence: dict[str, list[dict]]
    next: str
    error: str | None
    summary: dict
    reflection_enabled: bool
