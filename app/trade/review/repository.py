"""검토 제안·선택·파일 저장. 상태 전이와 문서 버전 확보를 하나의 트랜잭션으로 처리한다.

회사 이미지는 제안이 file ID로 고정하고 렌더 때 Storage에서 bytes를 읽는다(계획 9절).
설정을 바꿔도 과거 제안은 같은 이미지를 쓴다.
"""
from copy import deepcopy
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select, update

from app.db.models import FileAsset, TradeArtifact, TradeDocument, TradeProposal, utcnow
from app.files.storage import StorageError
from app.services.locks import user_lock
from app.trade.settings.repository import PNG_MAGIC, branding_file_assets, download_verified_image
from app.trade.common.models import DocumentError
from app.trade.common.repository import SQLDocuments
from app.trade.common.results import artifact_view
from app.trade.review.models import Branding, BrandingFiles


def _image_document_error(error: StorageError) -> DocumentError:
    """Storage 장애와 이미지 손상을 구분해 둘 다 성공으로 돌려주지 않는다(계획 9절)."""
    code = "IMAGE_CORRUPTED" if error.code == "image_corrupted" else "STORAGE_UNAVAILABLE"
    return DocumentError(code, error.message, 503)


class SQLReviews:
    def __init__(self, database, user_id, document_type, storage=None):
        self.database, self.user_id, self.document_type = database, user_id, document_type
        self.storage = storage
        self.documents = SQLDocuments(database, user_id, document_type)

    def document(self, document_id):
        return self.documents.get(document_id)

    def branding(self):
        with self.database.session() as session:
            logo_asset, seal_asset = branding_file_assets(session, self.user_id)
        if seal_asset is None:
            raise DocumentError("SEAL_REQUIRED", "회사 직인이 업로드되지 않았습니다. 설정에서 직인을 업로드해 주세요.", 409)
        try:
            seal = download_verified_image(self.storage, seal_asset)
            logo = download_verified_image(self.storage, logo_asset) if logo_asset is not None else None
        except StorageError as error:
            raise _image_document_error(error) from error
        if not seal.startswith(PNG_MAGIC):
            raise DocumentError("SEAL_REQUIRED", "저장된 회사 직인이 PNG 이미지가 아닙니다. 직인을 다시 업로드해 주세요.", 409)
        return Branding(seal=seal, logo=logo, seal_file_id=seal_asset.id,
                        logo_file_id=logo_asset.id if logo_asset is not None else None)

    def _proposal_asset(self, session, file_id):
        """제안이 고정한 이미지 파일. 없거나 타인 소유면 더 읽지 않고 실패시킨다(성공 아님)."""
        if file_id is None:
            raise DocumentError("IMAGE_UNAVAILABLE",
                                "제안이 가리키는 회사 이미지를 찾을 수 없습니다. 관리자에게 문의해 주세요.", 503)
        asset = session.get(FileAsset, file_id)
        if asset is None or asset.user_id != self.user_id:
            raise DocumentError("IMAGE_UNAVAILABLE",
                                "제안이 가리키는 회사 이미지를 찾을 수 없습니다. 관리자에게 문의해 주세요.", 503)
        return asset

    def proposal_branding(self, proposal):
        files = proposal["branding"]
        try:
            with self.database.session() as session:
                seal_asset = self._proposal_asset(session, files.seal_file_id)
                logo_asset = (self._proposal_asset(session, files.logo_file_id)
                              if files.logo_file_id is not None else None)
                seal = download_verified_image(self.storage, seal_asset)
                logo = download_verified_image(self.storage, logo_asset) if logo_asset is not None else None
        except StorageError as error:
            raise _image_document_error(error) from error
        return Branding(seal=seal, logo=logo, seal_file_id=files.seal_file_id,
                        logo_file_id=files.logo_file_id)

    def _owned(self, session, proposal_id):
        row = session.scalar(select(TradeProposal).join(TradeDocument).where(
            TradeProposal.id == proposal_id, TradeProposal.user_id == self.user_id,
            TradeDocument.user_id == self.user_id, TradeDocument.doc_kind == self.document_type))
        if row is None:
            raise DocumentError("PROPOSAL_NOT_FOUND", "검토 제안을 찾을 수 없습니다", 404)
        return row

    def _view(self, session, row):
        files = session.scalars(select(TradeArtifact).where(
            TradeArtifact.proposal_id == row.id, TradeArtifact.user_id == self.user_id,
        ).order_by(TradeArtifact.file_format)).all()
        return {"id": row.id, "document_id": row.document_id, "revision": row.revision,
                "payload": deepcopy(row.payload), "content_hash": row.content_hash,
                "status": row.status, "decision": row.decision,
                "created_at": row.created_at.isoformat(),
                "decided_at": row.decided_at.isoformat() if row.decided_at else None,
                "branding": BrandingFiles(seal_file_id=row.seal_file_id, logo_file_id=row.logo_file_id),
                "files": [artifact_view(file) for file in files]}

    def create(self, document_id, revision, payload, content_hash, branding):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            matched = session.execute(update(TradeDocument).where(
                TradeDocument.id == document_id, TradeDocument.user_id == self.user_id,
                TradeDocument.doc_kind == self.document_type, TradeDocument.revision == revision,
                TradeDocument.status == "ready",
            ).values(status="ready")).rowcount
            if matched != 1:
                raise DocumentError("REVISION_CONFLICT", "최신 문서를 다시 확인하세요")
            session.execute(update(TradeProposal).where(
                TradeProposal.document_id == document_id, TradeProposal.user_id == self.user_id,
                TradeProposal.status == "pending",
            ).values(status="superseded", decided_at=utcnow()))
            row = TradeProposal(id=uuid4().hex, user_id=self.user_id, document_id=document_id,
                                revision=revision, payload=deepcopy(payload), content_hash=content_hash,
                                status="pending", logo_file_id=branding.logo_file_id,
                                seal_file_id=branding.seal_file_id)
            session.add(row)
            session.flush()
            return self._view(session, row)

    def get(self, proposal_id):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            return self._view(session, self._owned(session, proposal_id))

    @staticmethod
    def _check(row, revision, content_hash):
        if row.revision != revision or row.content_hash != content_hash:
            raise DocumentError("PROPOSAL_MISMATCH", "확인한 검토 제안과 일치하지 않습니다")

    def cancel(self, proposal_id, revision, content_hash):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            row = self._owned(session, proposal_id)
            self._check(row, revision, content_hash)
            if row.status == "cancelled":
                return self._view(session, row)
            claimed = session.execute(update(TradeProposal).where(
                TradeProposal.id == row.id, TradeProposal.user_id == self.user_id,
                TradeProposal.status == "pending", TradeProposal.revision == revision,
                TradeProposal.content_hash == content_hash,
            ).values(status="cancelled", decision="cancel", decided_at=utcnow())
                .execution_options(synchronize_session=False)).rowcount
            if claimed != 1:
                raise DocumentError("PROPOSAL_CONFLICT", "이미 처리되거나 대체된 검토 제안입니다")
            session.refresh(row)
            return self._view(session, row)

    def approve(self, proposal_id, revision, content_hash, files):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            row = self._owned(session, proposal_id)
            self._check(row, revision, content_hash)
            if row.status == "approved":
                return self._view(session, row)
            matched = session.execute(update(TradeDocument).where(
                TradeDocument.id == row.document_id, TradeDocument.user_id == self.user_id,
                TradeDocument.doc_kind == self.document_type, TradeDocument.revision == revision,
                TradeDocument.status == "ready",
            ).values(status="issued", draft={**row.payload["document"], "status": "issued"})).rowcount
            if matched != 1:
                session.refresh(row)
                if row.status == "approved":
                    return self._view(session, row)
                raise DocumentError("REVISION_CONFLICT", "최신 문서를 다시 확인하세요")
            claimed = session.execute(update(TradeProposal).where(
                TradeProposal.id == row.id, TradeProposal.user_id == self.user_id,
                TradeProposal.status == "pending", TradeProposal.revision == revision,
                TradeProposal.content_hash == content_hash,
            ).values(status="approved", decision="approve", decided_at=utcnow())
                .execution_options(synchronize_session=False)).rowcount
            if claimed != 1:
                raise DocumentError("PROPOSAL_CONFLICT", "이미 처리되거나 대체된 검토 제안입니다")
            session.add_all([TradeArtifact(
                id=uuid4().hex, user_id=self.user_id, proposal_id=row.id, file_format=file.file_format,
                filename=file.filename, media_type=file.media_type, content=file.content,
                content_hash=sha256(file.content).hexdigest()) for file in files])
            session.flush()
            session.refresh(row)
            return self._view(session, row)

    def file(self, file_id):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            row = session.scalar(select(TradeArtifact).join(TradeProposal).where(
                TradeArtifact.id == file_id, TradeArtifact.user_id == self.user_id,
                TradeProposal.user_id == self.user_id, TradeProposal.status == "approved"))
            if row is None:
                raise DocumentError("FILE_NOT_FOUND", "확정된 파일을 찾을 수 없습니다", 404)
            return {"filename": row.filename, "media_type": row.media_type,
                    "content_hash": row.content_hash, "content": row.content}
