from copy import deepcopy

from sqlalchemy import select

from app.db.models import TradeDocument, TradeDocumentVersion, TradeProposal
from app.services.locks import user_lock
from app.trade.common.models import DocumentError
from app.trade.common.repository import SQLDocuments


class SQLCI(SQLDocuments):
    def source_pi(self, document_id, revision):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            version = session.scalar(select(TradeDocumentVersion).join(
                TradeDocument, TradeDocument.id == TradeDocumentVersion.document_id).where(
                TradeDocument.id == document_id, TradeDocument.user_id == self.user_id,
                TradeDocument.doc_kind == "PI", TradeDocumentVersion.user_id == self.user_id,
                TradeDocumentVersion.revision == revision))
            if version is None:
                raise DocumentError("SOURCE_PI_NOT_FOUND", "선택한 PI 버전을 찾을 수 없습니다", 404)
            approved = session.scalar(select(TradeProposal.id).where(
                TradeProposal.document_id == document_id, TradeProposal.user_id == self.user_id,
                TradeProposal.revision == revision, TradeProposal.status == "approved").limit(1))
            if approved is None:
                raise DocumentError("SOURCE_PI_NOT_APPROVED", "먼저 선택한 PI 버전을 검토하고 승인하세요")
            return deepcopy(version.payload)


def ci_repository(database, user_id):
    return SQLCI(database, user_id, "CI")
