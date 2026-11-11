"""사용자·문서 종류로 범위가 고정된 SQL 저장 구현. 업무 정책은 호출하지 않는다."""
from datetime import datetime, timedelta, timezone
from copy import deepcopy

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.db.models import CompanyBankAccount, CompanyProfile, TradeDocument, User
from app.services.locks import user_lock
from app.trade.common.models import DocumentContext, DocumentError
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
                    return deepcopy(row.draft)
            except IntegrityError:
                if attempt == 2:
                    raise

    def replace(self, document_id, revision, document):
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
            return result
