"""인증된 호출자를 받는 시작/조회/재개 경계."""

from collections import defaultdict
from copy import deepcopy
from threading import RLock

from langgraph.types import Command

from app.graph.build import build_workflow
from app.graph.master.context import Dependencies, _ExecutionGrant, execution_grant
from app.graph.schemas import Answer, Approval, Plan, PreparedAction, WorkflowError, WorkResult


class Workflow:
    def __init__(self, *, dependencies: Dependencies, checkpointer):
        self._graph = build_workflow(dependencies=dependencies, checkpointer=checkpointer)
        self._locks = defaultdict(RLock)

    @staticmethod
    def _config(thread_id: str):
        if not thread_id or len(thread_id) > 128:
            raise WorkflowError("invalid_thread_id")
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": 512}

    def _owned(self, actor_id: int, thread_id: str):
        snapshot = self._graph.get_state(self._config(thread_id))
        if not snapshot.values or snapshot.values["actor_id"] != actor_id:
            raise WorkflowError("workflow_not_found")
        return snapshot

    def start(self, *, actor_id: int, thread_id: str, request: str = "", plan: Plan | None = None,
              reflection_enabled: bool = True):
        """actor_id는 인증 경계에서 공급한다. 요청 본문/모델이 정한 소유자를 받지 않는다."""
        config = self._config(thread_id)
        with self._locks[thread_id]:
            if self._graph.get_state(config).values:
                raise WorkflowError("thread_already_exists")
            tasks = Plan.model_validate(plan).model_dump(mode="json")["tasks"] if plan is not None else []
            initial = dict(actor_id=actor_id, thread_id=thread_id, request=request,
                           memory={}, tasks=tasks, results={}, current=None, work=None,
                           rounds={}, repairs={}, attempts={}, actions={}, evidence={}, next="",
                           error=None, summary={}, reflection_enabled=reflection_enabled)
            return self._graph.invoke(initial, config=config, durability="sync")

    def inspect(self, *, actor_id: int, thread_id: str):
        with self._locks[thread_id]:
            return deepcopy(self._owned(actor_id, thread_id).values)

    def resume(self, *, actor_id: int, thread_id: str, response: dict):
        with self._locks[thread_id]:
            snapshot = self._owned(actor_id, thread_id)
            state = snapshot.values
            if not snapshot.next:
                if "action_id" in response:
                    approval = Approval.model_validate(response)
                    recorded = state["actions"].get(approval.action_id)
                    if recorded is None or PreparedAction.model_validate(recorded).content_hash != approval.content_hash:
                        raise WorkflowError("approval_mismatch")
                return deepcopy(state)
            grant = None
            if snapshot.next == ("await_approval",):
                action = PreparedAction.model_validate(state["work"]["action"])
                approval = Approval.model_validate(response)
                if (approval.action_id, approval.content_hash) != (action.id, action.content_hash):
                    raise WorkflowError("approval_mismatch")
                if approval.decision == "approve":
                    grant = _ExecutionGrant(thread_id, action.id, action.content_hash)
            elif snapshot.next == ("ask_user",):
                answer = Answer.model_validate(response)
                question = state["work"]["question"]
                if answer.task_id != state["current"] or not answer.answers or not set(answer.answers) <= set(question["fields"]):
                    raise WorkflowError("invalid_answer")
            else:
                raise WorkflowError("use_recover_for_interrupted_execution")
            token = execution_grant.set(grant)
            try:
                return self._graph.invoke(Command(resume=response), config=self._config(thread_id), durability="sync")
            finally:
                execution_grant.reset(token)

    def recover(self, *, actor_id: int, thread_id: str):
        """새 승인 없이 쓰지 않는다. 완료 불명 작업은 같은 action의 영수증만 다시 읽는다."""
        with self._locks[thread_id]:
            snapshot = self._owned(actor_id, thread_id)
            state = snapshot.values
            if snapshot.next in {("ask_user",), ("await_approval",)}:
                return deepcopy(state)
            config = self._config(thread_id)
            if not snapshot.next:
                unknown = next((key for key, value in state["results"].items() if value["status"] == "unknown"), None)
                if unknown is None:
                    return deepcopy(state)
                action = next(PreparedAction.model_validate(raw) for key, raw in state["actions"].items()
                              if raw["task_id"] == unknown and key in state["attempts"])
                results = {key: value for key, value in state["results"].items()
                           if key != unknown and value["status"] != "blocked"}
                self._graph.update_state(config, {"current": unknown, "results": results,
                    "work": WorkResult(status="needs_approval", action=action).model_dump(mode="json")},
                    as_node="mark_execution")
            token = execution_grant.set(None)
            try:
                return self._graph.invoke(None, config=config, durability="sync")
            finally:
                execution_grant.reset(token)
