"""문서 조회·작성·발급 제안. 계산/원본 검증/렌더링은 기존 문서 업무에 맡긴다."""

from typing import Protocol
from datetime import datetime, timezone

from app.graph.documents.schemas import DocumentInput
from app.graph.schemas import Evidence, ExecutionResult, PreparedAction, Question, WorkResult, content_hash


def document_evidence(kind, document_id, revision, document):
    return [Evidence(source="stored_document", reference=f"{kind}:{document_id}",
                     version=f"{revision}:{content_hash(document)}", observed_at=datetime.now(timezone.utc).isoformat())]


class DocumentPort(Protocol):
    def get(self, actor_id: int, command: DocumentInput) -> dict: ...
    def draft(self, actor_id: int, command: DocumentInput) -> dict: ...
    def propose(self, actor_id: int, command: DocumentInput, *, packing: bool = False) -> dict: ...
    def recheck(self, actor_id: int, action: PreparedAction) -> None: ...
    def issue(self, actor_id: int, action: PreparedAction) -> ExecutionResult: ...
    def lookup(self, actor_id: int, action: PreparedAction) -> ExecutionResult: ...
    def cancel(self, actor_id: int, action: PreparedAction) -> None: ...


class DocumentNodes:
    operations = frozenset({"get", "draft", "approve_packing", "issue"})

    def __init__(self, port: DocumentPort):
        self.port = port

    def prepare(self, task, context):
        if task.inputs.get("kind") is None:
            return WorkResult(status="needs_input", question=Question(fields=["kind"], message="문서 종류를 선택해 주세요."))
        command = DocumentInput.model_validate(task.inputs)
        if task.operation in {"get", "approve_packing", "issue"} and command.document_id is None:
            return WorkResult(status="needs_input", question=Question(fields=["document_id"], message="대상 문서를 선택해 주세요."))
        if task.operation == "get":
            if command.values is not None or command.text is not None:
                return WorkResult(status="failed", code="use_draft_to_modify_document")
            data = self.port.get(context.actor_id, command)
            return WorkResult(status="completed", data=data, evidence=document_evidence(
                command.kind, data["document_id"], data["revision"], data["document"]))
        if task.operation == "draft":
            if command.values is None and command.text is None:
                return WorkResult(status="needs_input", question=Question(fields=["values", "text"], message="문서 입력값 또는 원문을 알려 주세요."))
            if command.document_id is not None and command.revision is None:
                return WorkResult(status="failed", code="revision_required")
            data = self.port.draft(context.actor_id, command)
            resume = {"document_id": data["document_id"], "revision": data["revision"]}
            evidence = document_evidence(command.kind, data["document_id"], data["revision"], data["document"])
            blocking = data["document"].get("blocking_issues", [])
            packing_only = blocking and all(message == "Confirm packing totals before final review"
                or message.startswith("Packing source discrepancy: ") for message in blocking)
            if command.kind == "PL" and packing_only:
                return WorkResult(status="completed", data={**data, "needs_packing_approval": True}, resume_inputs=resume, evidence=evidence)
            if data["status"] != "ready":
                # 계산된 실제 누락/충돌과 기존 문서 ID를 보존하여 보완 때 새 문서를 만들지 않는다.
                return WorkResult(status="needs_input", data=data, resume_inputs=resume, evidence=evidence,
                    question=Question(fields=["values"], message="누락값과 오류를 확인해 문서 입력값을 보완해 주세요."))
            return WorkResult(status="completed", data=data, resume_inputs=resume, evidence=evidence)
        if task.operation == "approve_packing" and command.kind != "PL":
            return WorkResult(status="failed", code="packing_requires_pl")
        if command.values is not None or command.text is not None:
            return WorkResult(status="failed", code="use_draft_to_modify_document")
        proposal = self.port.propose(context.actor_id, command, packing=task.operation == "approve_packing")
        action = context.action(task, proposal, version=str(proposal["revision"]))
        return WorkResult(status="needs_approval", action=action, evidence=document_evidence(
            command.kind, proposal["document_id"], proposal["revision"], proposal["preview"]["document"]))

    def recheck(self, action, context):
        self.port.recheck(context.actor_id, action)
        return WorkResult(status="needs_approval", action=action, evidence=document_evidence(
            action.payload["kind"], action.payload["document_id"], action.payload["revision"], action.payload["preview"]["document"]))

    def execute(self, action, context):
        return self.port.issue(context.actor_id, action)

    def lookup(self, action, context):
        return self.port.lookup(context.actor_id, action)

    def cancel(self, action, context):
        return self.port.cancel(context.actor_id, action)
