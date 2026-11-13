"""마스터와 일정 계약: 실제 API 없이 실제 체크포인트/interrupt/재개를 검증한다."""

from copy import deepcopy
from datetime import datetime, timezone

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError
import pytest

from app.graph.calendar.nodes import CalendarNodes
from app.graph.calendar.schemas import BusySnapshot, Interval
from app.graph.master.context import Dependencies
from app.graph.master.runtime import Workflow
from app.graph.schemas import (
    ExecutionResult, InputRef, Plan, PreparedAction, Task, WorkResult, WorkflowError, content_hash,
)

QUERY = {"start": "2026-11-13T09:00:00+00:00", "end": "2026-11-13T13:00:00+00:00",
         "timezone": "UTC", "duration_minutes": 60, "calendar_ids": ["primary"],
         "participants": ["guest@example.invalid"]}


def fixed_clock():
    return datetime(2026, 11, 12, tzinfo=timezone.utc)


class FakeCalendar:
    def __init__(self):
        self.busy = {"primary": []}
        self.reads = self.writes = self.lookups = 0
        self.receipts = {}
        self.read_error = self.write_error = None
        self.epoch = 1

    def read_busy(self, actor_id, query):
        self.reads += 1
        if self.read_error:
            raise self.read_error
        return BusySnapshot(calendars=self.busy, version=content_hash({"busy": self.busy, "epoch": self.epoch}),
                            observed_at=datetime.now(timezone.utc))

    def create(self, actor_id, action):
        self.writes += 1
        if action.id in self.receipts:
            if self.receipts[action.id].content_hash != action.content_hash:
                raise WorkflowError("idempotency_conflict")
            return self.receipts[action.id]
        receipt = ExecutionResult(status="succeeded", action_id=action.id, content_hash=action.content_hash,
                                  receipt={"event_id": "event-1", "slot": action.payload["slot"]})
        self.receipts[action.id] = receipt
        if self.write_error:
            raise self.write_error
        return receipt

    def lookup(self, actor_id, action):
        self.lookups += 1
        return self.receipts.get(action.id, ExecutionResult(status="unknown", action_id=action.id,
                                                           content_hash=action.content_hash))


def workflow(port=None, **dependencies):
    port = port if port is not None else FakeCalendar()
    deps = Dependencies(handlers={"calendar": CalendarNodes(port, clock=fixed_clock)}, **dependencies)
    return Workflow(dependencies=deps, checkpointer=InMemorySaver()), port


def start(engine, operation="create", inputs=None, **kwargs):
    inputs = {**QUERY, "title": "가상 업무 회의", "selected_start": QUERY["start"]} if inputs is None else inputs
    return engine.start(actor_id=1, thread_id="workflow-1", plan=Plan(tasks=[
        Task(id="meeting", domain="calendar", operation=operation, inputs=inputs),
    ]), **kwargs)


def decision(state, choice="approve", **kwargs):
    action = PreparedAction.model_validate(state["work"]["action"])
    return {"action_id": action.id, "content_hash": action.content_hash, "decision": choice, **kwargs}


def resume(engine, response, actor_id=1):
    return engine.resume(actor_id=actor_id, thread_id="workflow-1", response=response)


def test_approval_is_required_and_repeated_response_does_not_create_twice():
    engine, port = workflow()
    state = start(engine)
    assert state["__interrupt__"][0].value["kind"] == "approval"
    assert port.writes == 0 and state["attempts"] == {}
    approval = decision(state)
    result = resume(engine, approval)
    assert result["results"]["meeting"]["status"] == "completed"
    assert result["results"]["meeting"]["data"]["event_id"] == "event-1"
    assert port.writes == 1
    assert resume(engine, approval)["results"] == result["results"]
    assert port.writes == 1
    with pytest.raises(WorkflowError, match="approval_mismatch"):
        resume(engine, {**approval, "content_hash": "wrong"})


@pytest.mark.parametrize("method", ["inspect", "resume", "recover"])
def test_other_actor_cannot_inspect_resume_or_recover(method):
    engine, port = workflow()
    state = start(engine)
    kwargs = {"actor_id": 2, "thread_id": "workflow-1"}
    if method == "resume":
        kwargs["response"] = decision(state)
    with pytest.raises(WorkflowError, match="workflow_not_found"):
        getattr(engine, method)(**kwargs)
    assert port.writes == 0


def test_question_resumes_only_requested_fields_and_keeps_prior_constraints():
    engine, port = workflow()
    state = start(engine, inputs={"title": "확정 제목"})
    assert state["__interrupt__"][0].value["fields"] == ["start", "end", "timezone", "duration_minutes", "calendar_ids"]
    assert port.reads == 0
    with pytest.raises(WorkflowError, match="invalid_answer"):
        resume(engine, {"task_id": "meeting", "answers": {"title": "다른 제목"}})
    state = resume(engine, {"task_id": "meeting", "answers": {key: QUERY[key] for key in
        ("start", "end", "timezone", "duration_minutes", "calendar_ids")}})
    assert state["work"]["question"]["fields"] == ["selected_start"]
    state = resume(engine, {"task_id": "meeting", "answers": {"selected_start": QUERY["start"]}})
    assert state["work"]["action"]["payload"]["query"]["title"] == "확정 제목"
    assert port.writes == 0


@pytest.mark.parametrize("changes", [
    {"start": "2026-11-14T09:00:00+00:00"}, {"timezone": "Unknown/Zone"},
    {"start": "2026-11-13T09:00:00"}, {"duration_minutes": 0}, {"participants": ["invalid"]},
])
def test_invalid_calendar_conditions_do_not_call_provider(changes):
    engine, port = workflow()
    state = start(engine, "find_slots", inputs={**QUERY, **changes})
    assert state["results"]["meeting"]["status"] == "failed"
    assert port.reads == port.writes == 0


def test_empty_slots_is_normal_but_incomplete_or_failed_lookup_is_not_empty():
    engine, port = workflow()
    port.busy = {"primary": [{"start": QUERY["start"], "end": QUERY["end"]}]}
    result = start(engine, "find_slots", inputs=QUERY)
    assert result["results"]["meeting"]["data"] == {"slots": [], "outcome": "no_slots"}
    assert result["results"]["meeting"]["status"] == "completed"
    for fail in ("incomplete", "transport"):
        engine, port = workflow()
        if fail == "incomplete":
            port.busy = {}
        else:
            port.read_error = TimeoutError("must not expose source text")
        result = start(engine, "find_slots", inputs=QUERY)
        assert result["results"]["meeting"]["status"] == "failed"
        assert "slots" not in result["results"]["meeting"]["data"]
        assert "must not expose" not in str(result)


def test_unavailable_calendar_does_not_report_success():
    engine = Workflow(dependencies=Dependencies(handlers={"calendar": CalendarNodes()}), checkpointer=InMemorySaver())
    result = start(engine, "find_slots", inputs=QUERY)
    assert result["results"]["meeting"]["code"] == "calendar_not_connected"


def test_current_preference_takes_priority_over_saved_preference():
    engine, _ = workflow(load_context=lambda actor, thread: {"preferences": {"calendar_preferred_hours": [12]}})
    result = start(engine, "find_slots", inputs={**QUERY, "preferred_hours": [10], "step_minutes": 60})
    slots = result["results"]["meeting"]["data"]["slots"]
    assert slots[0]["start"] == "2026-11-13T10:00:00Z"


def test_modification_invalidates_previous_approval():
    engine, port = workflow()
    old = start(engine)
    changed = resume(engine, decision(old, "modify", changes={"title": "수정한 제목"}))
    assert decision(changed)["content_hash"] != decision(old)["content_hash"]
    with pytest.raises(WorkflowError, match="approval_mismatch"):
        resume(engine, decision(old))
    assert port.writes == 0
    result = resume(engine, decision(changed))
    assert result["results"]["meeting"]["status"] == "completed" and port.writes == 1


def test_conflict_found_at_recheck_asks_for_new_selection_without_creating():
    engine, port = workflow()
    state = start(engine)
    port.busy["primary"] = [{"start": QUERY["start"], "end": "2026-11-13T10:00:00+00:00"}]
    changed = resume(engine, decision(state))
    assert changed["work"]["code"] == "slot_unavailable" and port.writes == 0
    selected = resume(engine, {"task_id": "meeting", "answers": {"selected_start": "2026-11-13T11:00:00+00:00"}})
    assert selected["work"]["status"] == "needs_approval"
    assert resume(engine, decision(selected))["results"]["meeting"]["status"] == "completed"


def test_source_version_change_requires_new_approval():
    engine, port = workflow()
    state = start(engine)
    port.epoch += 1
    changed = resume(engine, decision(state))
    assert changed["work"]["status"] == "needs_approval" and port.writes == 0
    assert decision(changed)["action_id"] != decision(state)["action_id"]
    assert resume(engine, decision(changed))["results"]["meeting"]["status"] == "completed"


def test_multiple_calendars_require_explicit_creation_target():
    engine, port = workflow()
    port.busy["team"] = []
    state = start(engine, inputs={**QUERY, "calendar_ids": ["primary", "team"],
        "title": "가상 회의", "selected_start": QUERY["start"]})
    assert state["work"]["question"]["fields"] == ["target_calendar_id"]
    state = resume(engine, {"task_id": "meeting", "answers": {"target_calendar_id": "team"}})
    assert state["work"]["action"]["payload"]["query"]["target_calendar_id"] == "team"
    assert port.writes == 0


def test_approval_of_a_slot_that_has_become_past_never_creates_event():
    now = [fixed_clock()]
    port = FakeCalendar()
    engine = Workflow(dependencies=Dependencies(handlers={"calendar": CalendarNodes(port, clock=lambda: now[0])}),
                      checkpointer=InMemorySaver())
    state = start(engine)
    now[0] = datetime(2026, 11, 14, tzinfo=timezone.utc)
    changed = resume(engine, decision(state))
    assert changed["work"]["code"] == "past_slot" and port.writes == 0


def test_recovery_rejects_receipt_for_another_payload():
    engine, port = workflow()
    port.write_error = TimeoutError()
    state = start(engine)
    result = resume(engine, decision(state))
    action_id = next(iter(port.receipts))
    port.receipts[action_id] = port.receipts[action_id].model_copy(update={"content_hash": "mismatch"})
    recovered = engine.recover(actor_id=1, thread_id="workflow-1")
    assert recovered["results"]["meeting"]["status"] == "unknown"
    assert port.writes == 1


@pytest.mark.parametrize("receipt_exists", [True, False])
def test_unknown_execution_uses_receipt_lookup_without_retrying_create(receipt_exists):
    engine, port = workflow()
    port.write_error = TimeoutError("response lost")
    state = start(engine)
    result = resume(engine, decision(state))
    assert result["results"]["meeting"]["status"] == "unknown" and port.writes == 1
    if not receipt_exists:
        port.receipts.clear()
    recovered = engine.recover(actor_id=1, thread_id="workflow-1")
    assert recovered["results"]["meeting"]["status"] == ("completed" if receipt_exists else "unknown")
    assert port.writes == 1 and port.lookups == 1


def test_checkpoint_recovery_has_no_saved_execution_authority():
    class SimulatedCrash(BaseException):
        pass

    engine, port = workflow()
    port.write_error = SimulatedCrash()
    state = start(engine)
    with pytest.raises(SimulatedCrash):
        resume(engine, decision(state))
    snapshot = engine.inspect(actor_id=1, thread_id="workflow-1")
    assert snapshot["attempts"]
    result = engine.recover(actor_id=1, thread_id="workflow-1")
    assert result["results"]["meeting"]["status"] == "completed"
    assert port.writes == port.lookups == 1


def test_pending_work_can_resume_from_another_runtime_with_same_checkpointer():
    saver, port = InMemorySaver(), FakeCalendar()
    dependencies = Dependencies(handlers={"calendar": CalendarNodes(port, clock=fixed_clock)})
    first = Workflow(dependencies=dependencies, checkpointer=saver)
    state = start(first)
    second = Workflow(dependencies=dependencies, checkpointer=saver)
    assert resume(second, decision(state))["results"]["meeting"]["status"] == "completed"
    assert port.writes == 1


@pytest.mark.parametrize("tasks", [
    [Task(id="same", domain="mail", operation="query")] * 2,
    [Task(id="a", domain="mail", operation="query", depends_on=["missing"])],
    [Task(id="a", domain="mail", operation="query", depends_on=["b"]), Task(id="b", domain="mail", operation="query", depends_on=["a"])],
    [Task(id="a", domain="mail", operation="query", bindings={"candidate_id": InputRef(task_id="b", field="id")})],
])
def test_invalid_dependency_graph_is_rejected(tasks):
    with pytest.raises(ValidationError):
        Plan(tasks=tasks)


class WorkOnly:
    operations = frozenset({"work"})

    def __init__(self, prepare):
        self.prepare = prepare

    def cancel(self, action, context):
        return None


def test_unordered_dependencies_bind_only_actual_results_and_propagate_cancel():
    observed = []

    def prepare(task, context):
        observed.append((task.id, deepcopy(task.inputs)))
        if task.id == "document":
            return WorkResult(status="completed", data={"document_id": 42})
        return WorkResult(status="needs_approval", action=context.action(task, task.inputs, version="1"))

    engine = Workflow(dependencies=Dependencies(handlers={"documents": WorkOnly(prepare), "mail": WorkOnly(prepare),
        "calendar": WorkOnly(prepare)}), checkpointer=InMemorySaver())
    plan = Plan(tasks=[
        Task(id="last", domain="calendar", operation="work", depends_on=["mail"]),
        Task(id="mail", domain="mail", operation="work", depends_on=["document"],
             bindings={"document_id": InputRef(task_id="document", field="document_id")}),
        Task(id="document", domain="documents", operation="work"),
    ])
    state = engine.start(actor_id=1, thread_id="workflow-1", plan=plan)
    assert observed == [("document", {}), ("mail", {"document_id": 42})]
    result = resume(engine, decision(state, "cancel"))
    assert result["results"]["mail"]["status"] == "cancelled"
    assert result["results"]["last"]["status"] == "blocked"


def test_reflection_cannot_change_confirmed_condition_and_off_switch_keeps_validation():
    calls = []

    def prepare(task, context):
        return WorkResult(status="needs_review", code="source_conflict", editable_fields=["title"])

    def repair(task, work, context):
        calls.append(task.id)
        return {"title": "모델이 바꾼 조건"}

    deps = Dependencies(handlers={"mail": WorkOnly(prepare)}, repair=repair)
    engine = Workflow(dependencies=deps, checkpointer=InMemorySaver())
    plan = Plan(tasks=[Task(id="mail", domain="mail", operation="work", inputs={"title": "확정"}, constraints={"title": "확정"})])
    result = engine.start(actor_id=1, thread_id="r1", plan=plan)
    assert result["results"]["mail"]["status"] == "needs_review"
    assert result["tasks"][0]["inputs"]["title"] == "확정" and calls == ["mail"]
    result = engine.start(actor_id=1, thread_id="r2", plan=plan, reflection_enabled=False)
    assert result["results"]["mail"]["status"] == "needs_review" and calls == ["mail"]
    engine, port = workflow()
    failed = start(engine, "find_slots", inputs={**QUERY, "duration_minutes": -1}, reflection_enabled=False)
    assert failed["results"]["meeting"]["status"] == "failed" and port.reads == 0


def test_reflection_budget_is_global_and_no_change_stops_the_loop():
    def prepare(task, context):
        return WorkResult(status="needs_review", editable_fields=["tone"])

    deps = Dependencies(handlers={"mail": WorkOnly(prepare)}, repair=lambda task, work, context: {"tone": task.inputs["tone"] + "x"})
    engine = Workflow(dependencies=deps, checkpointer=InMemorySaver())
    tasks = [Task(id=f"mail-{n}", domain="mail", operation="work", inputs={"tone": "x"}) for n in range(2)]
    result = engine.start(actor_id=1, thread_id="budget", plan=Plan(tasks=tasks))
    assert sum(result["repairs"].values()) == 3
    assert result["rounds"] == {"mail-0": 4, "mail-1": 1}


def test_planner_and_context_failures_do_not_become_user_questions():
    def broken(*args):
        raise WorkflowError("structured_invalid_output")

    for dependencies in (Dependencies(handlers={}, planner=broken), Dependencies(handlers={}, load_context=broken)):
        engine = Workflow(dependencies=dependencies, checkpointer=InMemorySaver())
        result = engine.start(actor_id=1, thread_id="failure", request="업무 요청")
        assert result["summary"]["error"] == "structured_invalid_output"
        assert "__interrupt__" not in result
