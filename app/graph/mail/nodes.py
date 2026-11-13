"""메일 준비와 발송 경계. 다른 업무 그래프를 직접 선택하지 않는다."""

from typing import Protocol
from datetime import datetime, timezone

from app.graph.mail.schemas import SendInput, ThreadInput
from app.graph.schemas import Evidence, ExecutionResult, PreparedAction, Question, WorkResult, content_hash


def candidate_evidence(snapshot):
    return [Evidence(source="reply_candidate", reference=str(snapshot["candidate_id"]),
                     version=snapshot["version"], observed_at=datetime.now(timezone.utc).isoformat())]


class MailPort(Protocol):
    def thread(self, actor_id: int, thread_id: str) -> dict: ...
    def draft(self, actor_id: int, thread_id: str) -> dict: ...
    def snapshot(self, actor_id: int, candidate_id: int, *, file_ids: list[str] | None = None) -> dict: ...
    def send(self, actor_id: int, action: PreparedAction) -> ExecutionResult: ...
    def lookup(self, actor_id: int, action: PreparedAction) -> ExecutionResult: ...


class MailNodes:
    operations = frozenset({"query", "draft", "send"})

    def __init__(self, port: MailPort):
        self.port = port

    def prepare(self, task, context):
        field = "candidate_id" if task.operation == "send" else "thread_id"
        if task.inputs.get(field) is None:
            return WorkResult(status="needs_input", question=Question(fields=[field], message="대상 메일 또는 답장 후보를 선택해 주세요."))
        if task.operation == "send":
            command = SendInput.model_validate(task.inputs)
            snapshot = self.port.snapshot(context.actor_id, command.candidate_id, file_ids=command.file_ids)
            if snapshot["status"] != "pending":
                return WorkResult(status="failed", code="candidate_not_pending")
            action = context.action(task, snapshot, version=snapshot["version"])
            return WorkResult(status="needs_approval", action=action, evidence=candidate_evidence(snapshot))
        command = ThreadInput.model_validate(task.inputs)
        if task.operation == "query":
            data = self.port.thread(context.actor_id, command.thread_id)
            observed = datetime.now(timezone.utc).isoformat()
            evidence = [Evidence(source="stored_thread", reference=message["gmail_message_id"],
                                 version=content_hash(message), observed_at=observed) for message in data["messages"]]
            return WorkResult(status="completed", data=data, evidence=evidence)
        result = self.port.draft(context.actor_id, command.thread_id)
        if result.get("end_reason") == "failed":
            return WorkResult(status="failed", code="draft_failed", data=result)
        return WorkResult(status="needs_review" if result.get("needs_review") else "completed", data=result)

    def recheck(self, action, context):
        snapshot = self.port.snapshot(context.actor_id, action.payload["candidate_id"], file_ids=action.payload["file_ids"])
        if snapshot != action.payload:
            return WorkResult(status="failed", code="candidate_changed")
        return WorkResult(status="needs_approval", action=action, evidence=candidate_evidence(snapshot))

    def execute(self, action, context):
        return self.port.send(context.actor_id, action)

    def lookup(self, action, context):
        return self.port.lookup(context.actor_id, action)

    def cancel(self, action, context):
        return None
