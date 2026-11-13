"""기존 Gmail 진입점의 변환기. 마스터에 발송 없는 수신 준비 작업을 등록한다."""

from langgraph.checkpoint.memory import InMemorySaver

from app.graph.master.context import Dependencies
from app.graph.master.inbound import build_inbound
from app.graph.master.runtime import Workflow
from app.graph.schemas import Plan, Task, WorkResult, WorkflowError


class InboundGraph:
    def __init__(self, *, node_overrides=None):
        self._inbound = build_inbound(node_overrides=node_overrides)

    def invoke(self, state, config=None):
        inbound = self._inbound

        class Preparation:
            operations = frozenset({"inbound"})

            def prepare(self, task, context):
                result = inbound.invoke(state, config=config)
                return WorkResult(status="completed", data={"legacy": result})

        # 수신 실행은 질문/발송을 재개하지 않는다. 승인 후보는 기존 DB/UI가 관리한다.
        workflow = Workflow(dependencies=Dependencies(handlers={"mail": Preparation()}), checkpointer=InMemorySaver())
        result = workflow.start(actor_id=state["user_id"], thread_id=state["run_id"],
            plan=Plan(tasks=[Task(id="inbound", domain="mail", operation="inbound")]))
        prepared = result["results"].get("inbound", {})
        if prepared.get("status") != "completed":
            raise WorkflowError("inbound_preparation_failed")
        return prepared["data"]["legacy"]
