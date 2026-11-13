"""작업 순서·질문·승인·실행 복구. ORM/HTTP/모델 생성은 주입된 경계에 있다."""

from copy import deepcopy

from langgraph.types import interrupt
from pydantic import ValidationError

from app.graph.master.context import Dependencies, WorkContext, execution_grant
from app.graph.schemas import (
    Answer, Approval, ExecutionResult, Plan, PreparedAction, Task, TaskResult,
    WorkResult, WorkflowError,
)


def current_task(state) -> Task:
    return next(Task.model_validate(task) for task in state["tasks"] if task["id"] == state["current"])


def work_context(state) -> WorkContext:
    return WorkContext(state["actor_id"], state["thread_id"],
                       state["rounds"].get(state["current"], 0),
                       deepcopy(state["memory"]), deepcopy(state["results"]))


def safe_failure(error: Exception) -> WorkResult:
    code = error.code if isinstance(error, WorkflowError) else "invalid_input" if isinstance(error, ValidationError) else "internal_error"
    return WorkResult(status="failed", code=code)


def action_of(state) -> PreparedAction:
    action = WorkResult.model_validate(state["work"]).action
    if action is None:
        raise WorkflowError("prepared_action_required")
    return action


def validate_action(state, result: WorkResult) -> WorkResult:
    if result.action is not None:
        task = current_task(state)
        action = result.action
        if (action.actor_id, action.task_id, action.domain, action.operation) != (
            state["actor_id"], task.id, task.domain, task.operation,
        ):
            raise WorkflowError("action_scope_mismatch")
    return result


class MasterNodes:
    def __init__(self, dependencies: Dependencies):
        self.dependencies = dependencies

    def load_context(self, state):
        try:
            return {"memory": self.dependencies.load_context(state["actor_id"], state["thread_id"])}
        except Exception as error:
            return {"error": safe_failure(error).code}

    def plan(self, state):
        if state["error"] or state["tasks"]:
            return {}
        try:
            if self.dependencies.planner is None:
                raise WorkflowError("planner_unavailable")
            plan = self.dependencies.planner(state["request"], work_context(state))
            return {"tasks": Plan.model_validate(plan).model_dump(mode="json")["tasks"]}
        except Exception as error:
            return {"error": safe_failure(error).code}

    def validate_plan(self, state):
        if state["error"]:
            return {"next": "finish"}
        try:
            plan = Plan(tasks=state["tasks"])
            for task in plan.tasks:
                handler = self.dependencies.handlers.get(task.domain)
                if handler is None or task.operation not in handler.operations:
                    raise WorkflowError("unsupported_operation")
                if any(task.inputs.get(key) != value for key, value in task.constraints.items()):
                    raise WorkflowError("constraint_mismatch")
            return {"next": "select_task"}
        except Exception as error:
            return {"error": safe_failure(error).code, "next": "finish"}

    def select_task(self, state):
        results = deepcopy(state["results"])
        # 계획 순서와 무관하게 실패/취소/불명 의존성을 전파한다.
        while True:
            blocked = [raw["id"] for raw in state["tasks"] if raw["id"] not in results
                       and any(dep in results and results[dep]["status"] != "completed" for dep in raw["depends_on"])]
            if not blocked:
                break
            results.update({key: TaskResult(status="blocked", code="dependency_not_completed").model_dump() for key in blocked})
        for raw in state["tasks"]:
            task = Task.model_validate(raw)
            if task.id in results:
                continue
            if any(dep in results and results[dep]["status"] != "completed" for dep in task.depends_on):
                results[task.id] = TaskResult(status="blocked", code="dependency_not_completed").model_dump()
                continue
            if all(dep in results for dep in task.depends_on):
                try:
                    inputs = deepcopy(task.inputs)
                    for key, ref in task.bindings.items():
                        # 명시적 의존 작업의 실제 산출물만 연결한다. LLM 예측값은 쓰지 않는다.
                        inputs[key] = deepcopy(results[ref.task_id]["data"][ref.field])
                    bound = task.model_copy(update={"inputs": inputs})
                    if any(inputs.get(key) != value for key, value in task.constraints.items()):
                        raise WorkflowError("constraint_mismatch")
                except (KeyError, WorkflowError):
                    results[task.id] = TaskResult(status="blocked", code="dependency_output_missing").model_dump()
                    continue
                tasks = [bound.model_dump(mode="json") if item["id"] == task.id else item for item in state["tasks"]]
                return {"current": task.id, "tasks": tasks, "results": results, "work": None,
                        "next": f"{task.domain}_prepare"}
        return {"results": results, "current": None, "next": "finish"}

    def prepare(self, state):
        task = current_task(state)
        rounds = {**state["rounds"], task.id: state["rounds"].get(task.id, 0) + 1}
        try:
            context = work_context({**state, "rounds": rounds})
            result = self.dependencies.handlers[task.domain].prepare(task, context)
            result = validate_action(state, WorkResult.model_validate(result))
        except Exception as error:
            result = safe_failure(error)
        inputs = {**task.inputs, **result.resume_inputs}
        if any(inputs.get(key) != value for key, value in task.constraints.items()):
            result = WorkResult(status="failed", code="constraint_mismatch")
            inputs = task.inputs
        updated = task.model_copy(update={"inputs": inputs})
        actions = dict(state["actions"])
        if result.action is not None:
            actions[result.action.id] = result.action.model_dump(mode="json")
        return {"work": result.model_dump(mode="json"), "rounds": rounds, "actions": actions,
                "tasks": [updated.model_dump(mode="json") if raw["id"] == task.id else raw for raw in state["tasks"]],
                "evidence": {**state["evidence"], task.id: [e.model_dump() for e in result.evidence]}}

    def inspect_result(self, state):
        result = WorkResult.model_validate(state["work"])
        destination = {"needs_input": "ask_user", "needs_approval": "await_approval"}.get(result.status, "record_result")
        if result.status == "needs_review" and state["reflection_enabled"] and self.dependencies.repair:
            used = state["repairs"].get(state["current"], 0)
            if used < self.dependencies.repair_limit and sum(state["repairs"].values()) < min(self.dependencies.repair_limit, 3):
                destination = "reflect"
        return {"next": destination}

    def reflect(self, state):
        task, work = current_task(state), WorkResult.model_validate(state["work"])
        repairs = {**state["repairs"], task.id: state["repairs"].get(task.id, 0) + 1}
        try:
            changes = self.dependencies.repair(task, work, work_context(state))
            if not changes or not set(changes) <= set(work.editable_fields) or set(changes) & set(task.constraints):
                raise WorkflowError("repair_rejected")
            inputs = {**task.inputs, **changes}
            if inputs == task.inputs:
                raise WorkflowError("repair_no_change")
            updated = Task.model_validate({**task.model_dump(mode="json"), "inputs": inputs})
            tasks = [updated.model_dump(mode="json") if item["id"] == task.id else item for item in state["tasks"]]
            return {"tasks": tasks, "repairs": repairs, "work": None, "next": f"{task.domain}_prepare"}
        except Exception:
            return {"repairs": repairs, "next": "record_result"}

    def ask_user(self, state):
        task, work = current_task(state), WorkResult.model_validate(state["work"])
        raw = interrupt({"kind": "question", "task_id": task.id, **work.question.model_dump()})
        answer = Answer.model_validate(raw)
        if answer.task_id != task.id or not answer.answers or not set(answer.answers) <= set(work.question.fields):
            raise WorkflowError("invalid_answer")
        # 사용자 수정은 새 준비/검증을 거치며 이전 승인 제안을 재사용하지 않는다.
        updated = Task.model_validate({**task.model_dump(mode="json"),
                                       "inputs": {**task.inputs, **answer.answers},
                                       "constraints": {**task.constraints, **answer.answers}})
        return {"tasks": [updated.model_dump(mode="json") if item["id"] == task.id else item for item in state["tasks"]],
                "work": None, "next": f"{task.domain}_prepare"}

    def await_approval(self, state):
        action = action_of(state)
        raw = interrupt({"kind": "approval", "action": action.model_dump(mode="json"),
                         "content_hash": action.content_hash})
        decision = Approval.model_validate(raw)
        if (decision.action_id, decision.content_hash) != (action.id, action.content_hash):
            raise WorkflowError("approval_mismatch")
        if decision.decision == "cancel":
            return {"next": "cancel_action"}
        if decision.decision == "modify":
            task = current_task(state)
            if not decision.changes or not set(decision.changes) <= set(task.inputs):
                raise WorkflowError("invalid_modification")
            inputs = {**task.inputs, **decision.changes}
            updated = task.model_copy(update={"inputs": inputs, "constraints": {**task.constraints, **decision.changes}})
            return {"tasks": [updated.model_dump(mode="json") if item["id"] == task.id else item for item in state["tasks"]],
                    "work": None, "next": f"{task.domain}_prepare"}
        return {"next": f"{action.domain}_recheck"}

    def cancel_action(self, state):
        action = action_of(state)
        try:
            self.dependencies.handlers[action.domain].cancel(action, work_context(state))
            results = {**state["results"], action.task_id: TaskResult(status="cancelled").model_dump()}
            return {"results": results, "work": None, "next": "select_task"}
        except Exception:
            return {"work": WorkResult(status="needs_review", code="cancel_unconfirmed").model_dump(),
                    "next": "record_result"}

    def recheck(self, state):
        action = action_of(state)
        try:
            checked = self.dependencies.handlers[action.domain].recheck(action, work_context(state))
            checked = validate_action(state, WorkResult.model_validate(checked))
            if checked.status == "needs_approval" and checked.action.content_hash == action.content_hash:
                return {"next": "mark_execution", "evidence": {**state["evidence"], action.task_id:
                    [e.model_dump() for e in checked.evidence] if checked.evidence else state["evidence"].get(action.task_id, [])}}
            # 변경된 내용에는 반드시 별도 승인을 받는다.
            return {"work": checked.model_dump(mode="json"), "next": "inspect_result",
                    "actions": {**state["actions"], **({checked.action.id: checked.action.model_dump(mode="json")} if checked.action else {})},
                    "evidence": {**state["evidence"], action.task_id: [e.model_dump() for e in checked.evidence]}}
        except Exception as error:
            return {"work": safe_failure(error).model_dump(), "next": "record_result"}

    def mark_execution(self, state):
        action = action_of(state)
        previous = state["attempts"].get(action.id)
        if previous is not None and previous != action.content_hash:
            raise WorkflowError("idempotency_conflict")
        return {"attempts": {**state["attempts"], action.id: action.content_hash},
                "actions": {**state["actions"], action.id: action.model_dump(mode="json")}}

    def execute(self, state):
        action = action_of(state)
        handler = self.dependencies.handlers[action.domain]
        grant = execution_grant.get()
        try:
            # 장애 뒤 재개/체크포인트 재생에는 새 발송 권한이 없다. 영수증 조회만 한다.
            if grant is not None and grant.consume(state["thread_id"], action):
                result = handler.execute(action, work_context(state))
            else:
                result = handler.lookup(action, work_context(state))
            result = ExecutionResult.model_validate(result)
            if (result.action_id, result.content_hash) != (action.id, action.content_hash):
                raise WorkflowError("receipt_mismatch")
        except Exception:
            result = ExecutionResult(status="unknown", action_id=action.id,
                                     content_hash=action.content_hash, code="execution_unconfirmed")
        status = {"succeeded": "completed", "failed": "failed", "unknown": "unknown"}[result.status]
        recorded = TaskResult(status=status, data=result.receipt, code=result.code).model_dump(mode="json")
        return {"results": {**state["results"], action.task_id: recorded}, "work": None}

    def record_result(self, state):
        work = WorkResult.model_validate(state["work"])
        if work.status not in {"completed", "failed", "needs_review"}:
            raise WorkflowError("unrecordable_result")
        recorded = TaskResult(status=work.status, data=work.data, code=work.code).model_dump(mode="json")
        return {"results": {**state["results"], state["current"]: recorded}, "work": None}

    def finish(self, state):
        return {"summary": {"error": state["error"], "tasks": deepcopy(state["results"])}}
