"""기존 Gmail/승인 서비스 연결. SQL과 Google 호출은 어댑터가 소유한다."""

from dataclasses import replace
from base64 import urlsafe_b64decode, urlsafe_b64encode
from email.parser import BytesParser
from email.policy import default as email_policy
from hashlib import sha256

from sqlalchemy import select

from app.db.models import (Approval, CompanyBranding, CompanyProfile, FileAsset, Quote, ReplyCandidate,
                           RunEvent, ThreadMessage, TradeArtifact, TradeDocument, TradeProposal)
from app.graph.schemas import ExecutionResult, WorkflowError, content_hash
from app.services.auth import get_access_token
from app.services import approval
from app.services.locks import user_lock
from app.runlog.logger import log_event
from app.trade.review.repository import SQLReviews
from app.trade.common.models import DocumentError


class _ApprovedGmail:
    """승인 스냅샷의 헤더/불변 발급 파일을 기존 claim·발송 서비스에 전달한다."""

    def __init__(self, google, message_id, headers, attachments):
        self.google, self.message_id, self.headers = google, message_id, headers
        self.attachments = attachments

    def get_reply_headers(self, gmail, message_id):
        if message_id != self.message_id:
            raise WorkflowError("source_message_mismatch")
        return dict(self.headers)

    def __getattr__(self, name):
        return getattr(self.google, name)

    def send_message(self, gmail, raw, thread_id):
        if self.attachments:
            message = BytesParser(policy=email_policy).parsebytes(urlsafe_b64decode(raw))
            for file in self.attachments:
                maintype, _, subtype = file["media_type"].partition("/")
                message.add_attachment(file["content"], maintype=maintype, subtype=subtype,
                                       filename=file["filename"])
            raw = urlsafe_b64encode(message.as_bytes()).decode()
        return self.google.send_message(gmail, raw, thread_id)


class ExistingMail:
    def __init__(self, *, database, access=None, storage=None):
        self.database, self.access = database, access
        self.storage = storage

    def thread(self, actor_id, thread_id):
        with self.database.session() as session:
            rows = session.scalars(select(ThreadMessage).where(
                ThreadMessage.user_id == actor_id, ThreadMessage.thread_id == thread_id,
            ).order_by(ThreadMessage.sent_at, ThreadMessage.id)).all()
            if not rows:
                raise WorkflowError("thread_not_found")
            return {"messages": [{"gmail_message_id": row.gmail_message_id, "thread_id": row.thread_id,
                                  "rfc_message_id": None, "from_addr": row.from_addr, "from_name": None,
                                  "to_addrs": row.to_addrs, "subject": row.subject, "body_text": row.body_text,
                                  "received_at": row.sent_at.isoformat(), "direction": row.direction} for row in rows]}

    def draft(self, actor_id, thread_id):
        from app.graph.run import start_run

        messages = self.thread(actor_id, thread_id)["messages"]
        email = next((message for message in reversed(messages) if message["direction"] == "in"), None)
        if email is None:
            raise WorkflowError("inbound_message_required")
        result = start_run(user_id=actor_id, email=email, database=self.database)
        with self.database.session() as session:
            ids = list(session.scalars(select(ReplyCandidate.id).where(
                ReplyCandidate.user_id == actor_id, ReplyCandidate.run_id == result["run_id"],
            ).order_by(ReplyCandidate.id)))
        return {"candidate_ids": ids, "run_id": result["run_id"], "end_reason": result["end_reason"],
                "needs_review": result["needs_review"]}

    def snapshot(self, actor_id, candidate_id, *, file_ids=None):
        file_ids = sorted(set(file_ids or []))
        with self.database.session() as session:
            row = session.scalar(select(ReplyCandidate).where(ReplyCandidate.id == candidate_id,
                                                             ReplyCandidate.user_id == actor_id))
            if row is None:
                raise WorkflowError("candidate_not_found")
            snapshot = {key: getattr(row, key) for key in (
                "run_id", "thread_id", "source_message_id", "subject", "body", "kind", "quote_id", "trade_doc_id", "status")}
            snapshot["candidate_id"] = row.id
            snapshot["file_ids"] = file_ids
            if file_ids and row.kind == "quote":
                raise WorkflowError("use_general_candidate_for_issued_files")
            files = session.execute(select(TradeArtifact, TradeDocument.doc_kind, TradeProposal.revision)
                .join(TradeProposal, TradeProposal.id == TradeArtifact.proposal_id)
                .join(TradeDocument, TradeDocument.id == TradeProposal.document_id)
                .where(TradeArtifact.id.in_(file_ids), TradeArtifact.user_id == actor_id,
                       TradeProposal.user_id == actor_id, TradeProposal.status == "approved",
                       TradeDocument.user_id == actor_id).order_by(TradeArtifact.id)).all() if file_ids else []
            if len(files) != len(file_ids):
                raise WorkflowError("issued_file_not_found")
            snapshot["files"] = [{"id": file.id, "kind": kind, "revision": revision,
                                  "filename": file.filename, "media_type": file.media_type,
                                  "content_hash": file.content_hash} for file, kind, revision in files]
            if row.quote_id is not None:
                quote = session.scalar(select(Quote).where(Quote.id == row.quote_id, Quote.user_id == actor_id))
                if quote is None or quote.status != "ready":
                    raise WorkflowError("document_not_ready")
                snapshot["document"] = quote.draft
            if row.trade_doc_id is not None:
                document = session.scalar(select(TradeDocument).where(TradeDocument.id == row.trade_doc_id,
                                                                      TradeDocument.user_id == actor_id))
                if document is None or document.status != "ready":
                    raise WorkflowError("document_not_ready")
                snapshot["document"], snapshot["revision"] = document.draft, document.revision
            company = session.get(CompanyProfile, actor_id)
            if company is not None and (row.trade_doc_id or row.quote_id):
                snapshot["company"] = {column.key: getattr(company, column.key) for column in company.__table__.columns
                                       if column.key not in {"created_at", "updated_at"}}
                branding = session.get(CompanyBranding, actor_id)
                if branding:
                    ids = [value for value in (branding.logo_file_id, branding.seal_file_id) if value is not None]
                    snapshot["branding"] = {"logo_id": branding.logo_file_id, "seal_id": branding.seal_file_id,
                        "legacy_logo_hash": sha256(branding.logo).hexdigest() if branding.logo else None,
                        "legacy_seal_hash": sha256(branding.seal).hexdigest() if branding.seal else None,
                        "assets": [{"id": asset.id, "hash": asset.sha256} for asset in session.scalars(
                            select(FileAsset).where(FileAsset.user_id == actor_id, FileAsset.id.in_(ids)).order_by(FileAsset.id))]}
        if self.access is None:
            raise WorkflowError("gmail_not_connected")
        gmail = self.access.google.gmail(get_access_token(self.access, actor_id))
        headers = self.access.google.get_reply_headers(gmail, snapshot["source_message_id"])
        snapshot["headers"] = {key: headers[key] for key in ("reply-to", "from", "message-id", "references") if headers.get(key)}
        snapshot["version"] = content_hash(snapshot)
        return snapshot

    def lookup(self, actor_id, action):
        with self.database.session() as session:
            row = session.scalar(select(Approval).where(Approval.user_id == actor_id,
                Approval.candidate_id == action.payload["candidate_id"]))
            if row is not None and row.send_status == "sent" and row.sent_message_id:
                events = session.scalars(select(RunEvent).where(RunEvent.run_id == action.payload["run_id"],
                                                               RunEvent.event == "workflow_receipt"))
                if any(event.detail == {"action_id": action.id, "content_hash": action.content_hash,
                                        "sent_message_id": row.sent_message_id} for event in events):
                    return ExecutionResult(status="succeeded", action_id=action.id, content_hash=action.content_hash,
                        receipt={"sent_message_id": row.sent_message_id, "candidate_id": row.candidate_id})
        return ExecutionResult(status="unknown", action_id=action.id, content_hash=action.content_hash, code="send_unconfirmed")

    def send(self, actor_id, action):
        if self.access is None:
            raise WorkflowError("gmail_not_connected")
        with user_lock(self.database, actor_id):
            if self.snapshot(actor_id, action.payload["candidate_id"], file_ids=action.payload["file_ids"]) != action.payload:
                return ExecutionResult(status="failed", action_id=action.id, content_hash=action.content_hash, code="candidate_changed")
            payload = action.payload
            attachments = []
            try:
                for file in payload["files"]:
                    stored = SQLReviews(self.database, actor_id, file["kind"], self.storage).file(file["id"])
                    if sha256(stored["content"]).hexdigest() != file["content_hash"]:
                        raise WorkflowError("issued_file_changed")
                    attachments.append({**file, "content": stored["content"]})
            except (DocumentError, WorkflowError) as error:
                return ExecutionResult(status="failed", action_id=action.id, content_hash=action.content_hash, code=error.code)
            access = replace(self.access, google=_ApprovedGmail(self.access.google, payload["source_message_id"], payload["headers"], attachments))
            if payload.get("trade_doc_id"):
                result = approval.send_approved_trade_document(actor_id, payload["trade_doc_id"], payload["candidate_id"], access=access, storage=self.storage)
            elif payload.get("quote_id"):
                result = approval.send_approved_quote(actor_id, payload["quote_id"], payload["candidate_id"], access=access)
            else:
                result = approval.send_approved_candidate(actor_id, payload["candidate_id"], access=access)
        if result.outcome == "sent":
            with self.database.session() as session:
                sent = session.scalar(select(Approval).where(Approval.user_id == actor_id,
                    Approval.candidate_id == payload["candidate_id"]))
                sent_id = sent.sent_message_id if sent is not None and sent.send_status == "sent" else None
            if sent_id is not None:
                log_event(payload["run_id"], "workflow_receipt", database=self.database,
                          detail={"action_id": action.id, "content_hash": action.content_hash, "sent_message_id": sent_id})
        if result.outcome in {"sent", "already_sent"}:
            return self.lookup(actor_id, action)
        status = "unknown" if result.outcome == "failed_unknown" else "failed"
        return ExecutionResult(status=status, action_id=action.id, content_hash=action.content_hash, code=result.outcome)
