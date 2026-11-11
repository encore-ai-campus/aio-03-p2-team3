"""사용자·문서 종류로 범위가 고정된 SQL 저장 구현. 업무 정책은 호출하지 않는다."""
from datetime import datetime, timedelta, timezone
from copy import deepcopy

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.db.models import CompanyBankAccount, CompanyProfile, TradeArtifact, TradeDocument, TradeDocumentVersion, TradeProposal, User, utcnow
from app.services.locks import user_lock
from app.trade.common.models import DocumentContext, DocumentError
from app.trade.common.results import artifact_view
from app.trade.store import counterparty_profiles, trade_price_rows

ISSUER_FIELDS = ("company_name", "legal_name_en", "business_no", "ceo_name", "contact", "address",
                 "phone", "email", "registration_details")
BANK_FIELDS = ("beneficiary", "bank_name", "branch", "swift", "account_number", "bank_address")


class SQLDocuments:
    def __init__(self, database, user_id: int, document_type: str):
        self.database, self.user_id, self.document_type = database, user_id, document_type

    def _owned(self, session, document_id):
        row = session.scalar(select(TradeDocument).where(
            TradeDocument.id == document_id, TradeDocument.user_id == self.user_id,
            TradeDocument.doc_kind == self.document_type))
        if row is None:
            raise DocumentError("DOCUMENT_NOT_FOUND", "문서를 찾을 수 없습니다", 404)
        return row

    @staticmethod
    def _snapshot(row):
        if not isinstance(row.draft, dict):
            raise DocumentError("INVALID_STORED_DOCUMENT", "저장된 문서 형식을 확인하세요")
        return {**deepcopy(row.draft), "trade_doc_id": row.id, "doc_no": row.doc_no,
                "doc_kind": row.doc_kind, "document_type": row.doc_kind,
                "revision": row.revision, "status": row.status}

    def context(self, currency):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            issuer = session.get(CompanyProfile, self.user_id)
            bank = session.scalar(select(CompanyBankAccount).where(
                CompanyBankAccount.user_id == self.user_id, CompanyBankAccount.currency == currency))
            return DocumentContext(
                issuer={key: getattr(issuer, key) for key in ISSUER_FIELDS} if issuer else {},
                bank={key.upper(): getattr(bank, key) for key in BANK_FIELDS} if bank else None,
                price_rows=trade_price_rows(session, self.user_id),
                counterparties=counterparty_profiles(session, self.user_id))

    def get(self, document_id):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            return self._snapshot(self._owned(session, document_id))

    def create(self, document):
        if document.get("document_type") != self.document_type:
            raise DocumentError("DOCUMENT_TYPE_MISMATCH", "문서 종류가 일치하지 않습니다", 400)
        today = datetime.now(timezone(timedelta(hours=9))).date()
        prefix = f"{self.document_type}-{today:%Y%m%d}-"
        for attempt in range(3):
            try:
                with user_lock(self.database, self.user_id), self.database.session() as session:
                    user = session.scalar(select(User).where(User.id == self.user_id).with_for_update())
                    if user is None:
                        raise DocumentError("USER_NOT_FOUND", "로그인이 필요합니다", 401)
                    numbers = session.scalars(select(TradeDocument.doc_no).where(
                        TradeDocument.user_id == self.user_id, TradeDocument.doc_no.startswith(prefix))).all()
                    sequence = max((int(number[len(prefix):]) for number in numbers), default=0) + 1
                    row = TradeDocument(user_id=self.user_id, thread_id="", run_id="", doc_kind=self.document_type,
                                        doc_no=f"{prefix}{sequence:03d}", draft=deepcopy(document),
                                        status=document["status"], revision=1)
                    session.add(row)
                    session.flush()
                    row.draft = self._snapshot(row)
                    session.add(TradeDocumentVersion(document_id=row.id, user_id=self.user_id,
                                                      revision=1, payload=deepcopy(row.draft)))
                    return deepcopy(row.draft)
            except IntegrityError:
                if attempt == 2:
                    raise

    def replace(self, document_id, revision, document, review_reference=None):
        if document.get("document_type") != self.document_type:
            raise DocumentError("DOCUMENT_TYPE_MISMATCH", "문서 종류가 일치하지 않습니다", 400)
        with user_lock(self.database, self.user_id), self.database.session() as session:
            row = self._owned(session, document_id)
            if row.revision != revision or row.status in {"sent", "sending"}:
                raise DocumentError("REVISION_CONFLICT", "최신 문서를 다시 확인하세요")
            result = {**deepcopy(document), "trade_doc_id": row.id, "doc_no": row.doc_no,
                      "doc_kind": self.document_type, "revision": revision + 1}
            claimed = session.execute(update(TradeDocument).where(
                TradeDocument.id == document_id, TradeDocument.user_id == self.user_id,
                TradeDocument.doc_kind == self.document_type, TradeDocument.revision == revision,
                TradeDocument.status.not_in(("sent", "sending")),
            ).values(draft=result, status=result["status"], revision=revision + 1)).rowcount
            if claimed != 1:
                raise DocumentError("REVISION_CONFLICT", "최신 문서를 다시 확인하세요")
            # 모든 복합 갱신은 문서 → 제안 순서로 잠근다(승인/수정 사이 교착 방지).
            if review_reference is not None:
                proposal_id, content_hash = review_reference
                proposal_claimed = session.execute(update(TradeProposal).where(
                    TradeProposal.id == proposal_id, TradeProposal.user_id == self.user_id,
                    TradeProposal.document_id == document_id, TradeProposal.revision == revision,
                    TradeProposal.status == "pending", TradeProposal.content_hash == content_hash,
                ).values(status="superseded", decision="modify", decided_at=utcnow())).rowcount
                if proposal_claimed != 1:
                    raise DocumentError("PROPOSAL_CONFLICT", "현재 대기 중인 검토 제안을 다시 확인하세요")
            session.add(TradeDocumentVersion(document_id=document_id, user_id=self.user_id,
                                              revision=revision + 1, payload=deepcopy(result)))
            session.execute(update(TradeProposal).where(
                TradeProposal.document_id == document_id, TradeProposal.user_id == self.user_id,
                TradeProposal.status == "pending",
            ).values(status="superseded", decided_at=utcnow()))
            return result

    def list(self, limit=50):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            rows = session.scalars(select(TradeDocument).where(
                TradeDocument.user_id == self.user_id, TradeDocument.doc_kind == self.document_type,
            ).order_by(TradeDocument.id.desc()).limit(limit)).all()
            return [self._snapshot(row) for row in rows]

    def version(self, document_id, revision):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            document = self._owned(session, document_id)
            row = session.get(TradeDocumentVersion, (document_id, revision))
            if row is None or row.user_id != self.user_id:
                raise DocumentError("VERSION_NOT_FOUND", "문서 버전을 찾을 수 없습니다", 404)
            return {**deepcopy(row.payload), "trade_doc_id": document_id, "revision": row.revision,
                    "document_type": document.doc_kind, "doc_kind": document.doc_kind, "doc_no": document.doc_no}

    def latest_review(self, document_id, revision):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            row = session.scalar(select(TradeProposal).where(
                TradeProposal.document_id == document_id, TradeProposal.user_id == self.user_id,
                TradeProposal.revision == revision, TradeProposal.status.in_(("pending", "approved")),
            ).order_by(TradeProposal.created_at.desc()).limit(1))
            files = []
            if row is not None and row.status == "approved":
                files = [artifact_view(file) for file in session.scalars(select(TradeArtifact).where(
                    TradeArtifact.proposal_id == row.id, TradeArtifact.user_id == self.user_id,
                ).order_by(TradeArtifact.file_format))]
            return {"proposal_id": row.id if row else None, "files": files}
