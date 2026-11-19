"""메일 준비와 발송 경계. 다른 업무 그래프를 직접 선택하지 않는다."""

from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from datetime import datetime, timezone

from app.mail.schemas import ComposeInput
from app.mail.errors import MailError

from app.graph.mail.schemas import (
    AttachmentInput, FollowupCancelInput, FollowupInput, FollowupListInput,
    ReplyEditInput, SearchInput, SendInput, SentMailSearch, ThreadInput,
)
from app.graph.schemas import Evidence, ExecutionResult, PreparedAction, Question, WorkResult, content_hash


def candidate_evidence(snapshot):
    return [Evidence(source="reply_candidate", reference=str(snapshot["candidate_id"]),
                     version=snapshot["version"], observed_at=datetime.now(timezone.utc).isoformat())]


class MailPort(Protocol):
    def search(self, actor_id: int, query: SearchInput) -> dict: ...
    def compose(self, actor_id: int, draft_id: str, command: ComposeInput) -> dict: ...
    def search_sent(self, actor_id: int, query: str) -> dict: ...
    def attachments(self, actor_id: int, command: AttachmentInput) -> dict: ...
    def register_followup(self, actor_id: int, command: FollowupInput) -> dict: ...
    def list_followups(self, actor_id: int, command: FollowupListInput) -> dict: ...
    def cancel_followup(self, actor_id: int, followup_id: int) -> dict: ...
    def reply_edit_target(self, actor_id: int, candidate_id: int) -> dict: ...
    def update_reply(self, actor_id: int, action: PreparedAction) -> ExecutionResult: ...
    def lookup_reply_edit(self, actor_id: int, action: PreparedAction) -> ExecutionResult: ...
    def thread(self, actor_id: int, thread_id: str) -> dict: ...
    def draft(self, actor_id: int, thread_id: str) -> dict: ...
    def snapshot(self, actor_id: int, candidate_id: int, *, file_ids: list[str] | None = None) -> dict: ...
    def send(self, actor_id: int, action: PreparedAction) -> ExecutionResult: ...
    def lookup(self, actor_id: int, action: PreparedAction) -> ExecutionResult: ...


class MailNodes:
    operations = frozenset({"search", "query", "draft", "send", "compose", "edit_reply",
                            "attachments", "search_sent", "register_followup", "list_followups", "cancel_followup"})

    def __init__(self, port: MailPort):
        self.port = port

    def prepare(self, task, context):
        if task.operation in {"attachments", "search_sent", "register_followup", "list_followups", "cancel_followup"}:
            try:
                return self.prepare_mail_lookup(task, context)
            except MailError as error:
                return WorkResult(status="failed", code=error.code)
        if task.operation == "edit_reply":
            return self.prepare_reply_edit(task, context)
        if task.operation == "compose":
            command = ComposeInput.model_validate(task.inputs)
            draft_id = uuid5(NAMESPACE_URL, f"compose/{context.actor_id}/{context.thread_id}/{task.id}").hex
            return WorkResult(status="completed", data={"compose_draft": self.port.compose(context.actor_id, draft_id, command)})
        if task.operation == "search":
            query = SearchInput.model_validate(task.inputs)
            return WorkResult(status="completed", data=self.port.search(context.actor_id, query))
        if (task.operation == "send" and context.memory.get("agent_mode")
                and "candidate_id" not in task.constraints):
            return WorkResult(status="needs_input", question=Question(fields=["candidate_id"],
                message="발송할 답장 후보를 직접 선택해 주세요. 다음 단계에서 실제 수신자와 첨부를 확인합니다."))
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

    def prepare_mail_lookup(self, task, context):
        recent = [result.get("data") or {} for result in context.results.values()]
        actor_id = context.actor_id
        if task.operation == "attachments":
            command = AttachmentInput.model_validate(task.inputs)
            observed = any(message["thread_id"] == command.thread_id
                           and message["gmail_message_id"] == command.message_id
                           for data in recent for message in data.get("messages", []))
            if not observed:
                return WorkResult(status="failed", code="mail_attachment_lookup_required")
            data = self.port.attachments(actor_id, command)
        elif task.operation == "search_sent":
            command = SentMailSearch.model_validate(task.inputs)
            data = self.port.search_sent(actor_id, command.query.strip())
        elif task.operation == "register_followup":
            command = FollowupInput.model_validate(task.inputs)
            observed = any(item["thread_id"] == command.thread_id for result in recent
                           for key in ("messages", "sent_threads", "threads") for item in result.get(key, []))
            if not observed:
                return WorkResult(status="failed", code="followup_mail_lookup_required")
            data = {"followups": [self.port.register_followup(actor_id, command)]}
        elif task.operation == "list_followups":
            data = self.port.list_followups(actor_id, FollowupListInput.model_validate(task.inputs))
        else:
            command = FollowupCancelInput.model_validate(task.inputs)
            observed = any(item["id"] == command.followup_id for result in recent for item in result.get("followups", []))
            if not observed:
                return WorkResult(status="failed", code="followup_lookup_required")
            data = {"followups": [self.port.cancel_followup(actor_id, command.followup_id)]}
        return WorkResult(status="completed", data=data)

    def prepare_reply_edit(self, task, context):
        proposed_for = task.inputs.get("_edit_source")
        command = ReplyEditInput.model_validate({key: value for key, value in task.inputs.items() if key != "_edit_source"})
        seen = {item["id"]: item for result in context.results.values()
                for item in (result.get("data") or {}).get("candidates", []) if item}
        selected = seen.get(command.candidate_id)
        if selected is None:
            return WorkResult(status="failed", code="candidate_lookup_required")
        candidates = [item for item in seen.values() if item["thread_id"] == selected["thread_id"]
                      and item["status"] in {"pending", "send_failed"}]
        confirmed = any((result.get("data") or {}).get("confirmed_edit_candidate_id") == command.candidate_id
                        for result in context.results.values())
        if len(candidates) > 1 and "candidate_id" not in task.constraints and not confirmed:
            return WorkResult(status="needs_input", data={"candidates": candidates},
                resume_inputs={"_edit_source": command.candidate_id}, question=Question(
                    fields=["candidate_id"], message="수정할 답장 후보를 골라 주세요."))
        original = self.port.reply_edit_target(context.actor_id, command.candidate_id)
        if original["status"] not in {"pending", "send_failed"} or any(
                original[key] != selected[key] for key in ("status", "subject", "body")):
            return WorkResult(status="failed", code="candidate_changed")
        if proposed_for is not None and proposed_for != command.candidate_id:
            return WorkResult(status="failed", code="reply_edit_reselect", data={
                "confirmed_edit_candidate_id": original["id"], "candidates": [original],
            })
        changes = {"subject": (command.subject or original["subject"]).strip(),
                   "body": (command.body or original["body"]).strip()}
        return WorkResult(status="needs_approval", action=context.action(
            task, {"original": original, "changes": changes}, version=content_hash(original)))

    def recheck(self, action, context):
        if action.operation == "edit_reply":
            original = self.port.reply_edit_target(context.actor_id, action.payload["original"]["id"])
            if original != action.payload["original"]:
                return WorkResult(status="failed", code="candidate_changed")
            return WorkResult(status="needs_approval", action=action)
        snapshot = self.port.snapshot(context.actor_id, action.payload["candidate_id"], file_ids=action.payload["file_ids"])
        if snapshot != action.payload:
            return WorkResult(status="failed", code="candidate_changed")
        return WorkResult(status="needs_approval", action=action, evidence=candidate_evidence(snapshot))

    def execute(self, action, context):
        if action.operation == "edit_reply":
            return self.port.update_reply(context.actor_id, action)
        return self.port.send(context.actor_id, action)

    def lookup(self, action, context):
        if action.operation == "edit_reply":
            return self.port.lookup_reply_edit(context.actor_id, action)
        return self.port.lookup(context.actor_id, action)

    def cancel(self, action, context):
        return None
