from copy import deepcopy

from sqlalchemy import select, tuple_

from app.db.models import TradeDocument, TradeDocumentVersion, TradeProposal
from app.services.locks import user_lock
from app.trade.common.models import DocumentError
from app.trade.common.repository import SQLDocuments
from app.trade.common.results import document_result


class SQLCI(SQLDocuments):
    def source_pis(self, *, cursor=None, source_pi_id=None, source_revision=None):
        version = TradeDocumentVersion
        approved = select(TradeProposal.id).where(
            TradeProposal.document_id == version.document_id,
            TradeProposal.user_id == self.user_id,
            TradeProposal.revision == version.revision,
            TradeProposal.status == "approved",
        ).exists()
        query = select(version, TradeDocument.revision, approved).join(
            TradeDocument, TradeDocument.id == version.document_id).where(
            TradeDocument.user_id == self.user_id, version.user_id == self.user_id,
            TradeDocument.doc_kind == "PI")
        if source_pi_id is not None:
            query = query.where(version.document_id == source_pi_id, version.revision == source_revision)
        else:
            query = query.where(version.revision == TradeDocument.revision)
        if cursor is not None:
            query = query.where(tuple_(version.document_id, version.revision) < cursor)
        query = query.order_by(version.document_id.desc(), version.revision.desc()).limit(51)
        with user_lock(self.database, self.user_id), self.database.session() as session:
            rows = session.execute(query).all()
            if source_pi_id is not None and not rows:
                raise DocumentError("SOURCE_PI_NOT_FOUND", "선택한 PI 버전을 찾을 수 없습니다", 404)
            items = []
            for saved, current_revision, is_approved in rows[:50]:
                payload = {**deepcopy(saved.payload), "trade_doc_id": saved.document_id,
                           "revision": saved.revision, "document_type": "PI"}
                result = document_result(payload)
                items.append({"source_pi_id": saved.document_id, "source_revision": saved.revision,
                              "document_number": payload.get("document_number"),
                              "currency": payload.get("currency"), "total": payload.get("total"),
                              "approved": is_approved, "current_revision": current_revision,
                              "missing_fields": result.missing_fields, "issues": result.issues})
            last = items[-1] if len(rows) > 50 else None
            return {"items": items, "next_cursor": (
                f"{last['source_pi_id']}:{last['source_revision']}" if last else None)}

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
