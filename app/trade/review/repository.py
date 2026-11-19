"""검토 제안·선택·파일 저장. 상태 전이와 문서 버전 확보를 하나의 트랜잭션으로 처리한다.

회사 이미지는 제안이 file ID로 고정하고 렌더 때 Storage에서 bytes를 읽는다(계획 9절).
설정을 바꿔도 과거 제안은 같은 이미지를 쓴다. 발급 파일 bytes는 Storage에만 두고(계획 10절)
승인은 ①렌더 ②모든 형식의 Storage 저장 ③SQL 트랜잭션 확정 순서를 따른다(계약 16.3절).
③이 실패하면 ready/pending을 유지하고 ②까지 끝난 객체는 미참조로 남는다(cleanup 명령).
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
from uuid import uuid4

from sqlalchemy import Date, and_, case, cast, func, or_, select, update

from app.db.models import FileAsset, TradeArtifact, TradeDocument, TradeDocumentVersion, TradeProposal, User, utcnow
from app.files.storage import StorageError
from app.files.locks import lock_object
from app.services.locks import user_lock
from app.trade.settings.repository import PNG_MAGIC, branding_file_assets, download_verified_image
from app.trade.common.models import DocumentError
from app.trade.common.repository import SQLDocuments
from app.trade.common.results import artifact_view
from app.trade.review.models import Branding, BrandingFiles, RenderedFile


def _image_document_error(error: StorageError) -> DocumentError:
    """Storage 장애와 이미지 손상을 구분해 둘 다 성공으로 돌려주지 않는다(계획 9절)."""
    code = "IMAGE_CORRUPTED" if error.code == "image_corrupted" else "STORAGE_UNAVAILABLE"
    return DocumentError(code, error.message, 503)


def issued_object_key(user_id: int, proposal_id: str, file_format: str, content_hash: str) -> str:
    """발급 파일의 결정적 불변 key(계약 16.3절). 같은 제안·형식·bytes는 항상 같은 key다."""
    return f"{user_id}/issued/{proposal_id}/{file_format}/{content_hash}"



class SQLReviews:
    def __init__(self, database, user_id, document_type, storage=None):
        self.database, self.user_id, self.document_type = database, user_id, document_type
        self.storage = storage
        self.documents = SQLDocuments(database, user_id, document_type)

    def document(self, document_id):
        return self.documents.get(document_id)

    def search_issued(self, *, document_number, counterparty, issued_from, issued_to):
        document = TradeDocumentVersion.payload
        number = func.coalesce(document["document_number"].as_string(),
                               TradeProposal.payload["document"]["document_number"].as_string())
        internal_number = func.coalesce(document["doc_no"].as_string(), TradeDocument.doc_no)
        party = case((TradeDocument.doc_kind == "PO", document["seller"]["legal_name"].as_string()),
                     else_=document["buyer"]["legal_name"].as_string())
        legacy = TradeProposal.payload["document"]
        party = func.coalesce(party, case(
            (TradeDocument.doc_kind == "PO", legacy["seller"]["legal_name"].as_string()),
            else_=legacy["buyer"]["legal_name"].as_string(),
        ))
        # Korea uses UTC+09:00. An interval also works with embedded PostgreSQL without tzdata.
        day = cast(func.timezone(timedelta(hours=9), TradeProposal.decided_at), Date)
        has_files = select(TradeArtifact.id).where(
            TradeArtifact.proposal_id == TradeProposal.id, TradeArtifact.user_id == self.user_id,
        ).exists()
        query = select(
            TradeProposal.id.label("proposal_id"), TradeProposal.document_id, TradeProposal.revision,
            TradeDocument.doc_kind.label("kind"), func.coalesce(number, internal_number).label("document_number"),
            party.label("counterparty"), day.label("issued_on"), TradeProposal.decided_at,
        ).select_from(TradeProposal).join(TradeDocument, TradeDocument.id == TradeProposal.document_id).outerjoin(
            TradeDocumentVersion, and_(
            TradeDocumentVersion.document_id == TradeProposal.document_id,
            TradeDocumentVersion.revision == TradeProposal.revision,
            TradeDocumentVersion.user_id == self.user_id,
        )).where(
            TradeDocument.user_id == self.user_id, TradeProposal.user_id == self.user_id,
            TradeProposal.status == "approved", TradeProposal.decided_at.is_not(None), has_files,
        )
        if self.document_type:
            query = query.where(TradeDocument.doc_kind == self.document_type)
        if document_number:
            query = query.where(or_(number.icontains(document_number, autoescape=True),
                                    internal_number.icontains(document_number, autoescape=True)))
        if counterparty:
            query = query.where(party.icontains(counterparty, autoescape=True))
        if issued_from:
            query = query.where(day >= issued_from)
        if issued_to:
            query = query.where(day <= issued_to)

        issued = query.order_by(TradeProposal.decided_at.desc(), TradeProposal.id.desc()).limit(10).subquery()
        files = select(issued, TradeArtifact.id, TradeArtifact.file_format, TradeArtifact.filename,
                       TradeArtifact.media_type, TradeArtifact.content_hash).join(
            TradeArtifact, TradeArtifact.proposal_id == issued.c.proposal_id,
        ).where(TradeArtifact.user_id == self.user_id).order_by(
            issued.c.decided_at.desc(), issued.c.proposal_id.desc(), TradeArtifact.file_format,
        )
        matches = {}
        with self.database.session() as session:
            for row in session.execute(files):
                proposal = matches.setdefault(row.proposal_id, {
                    "proposal_id": row.proposal_id, "document_id": row.document_id, "revision": row.revision,
                    "kind": row.kind, "document_number": row.document_number, "counterparty": row.counterparty,
                    "issued_on": row.issued_on.isoformat(), "files": [],
                })
                proposal["files"].append(artifact_view(row))
        return {"issued_documents": list(matches.values())}

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
        version = session.get(TradeDocumentVersion, (row.document_id, row.revision)) if row.status == "approved" else None
        return {"id": row.id, "document_id": row.document_id, "revision": row.revision,
                "payload": deepcopy(row.payload), "content_hash": row.content_hash,
                "status": row.status, "decision": row.decision,
                "created_at": row.created_at.isoformat(),
                "decided_at": row.decided_at.isoformat() if row.decided_at else None,
                "issued_document_number": (version.payload or {}).get("document_number") if version else None,
                "branding": BrandingFiles(seal_file_id=row.seal_file_id, logo_file_id=row.logo_file_id),
                "files": [artifact_view(file) for file in files]}

    def create(self, document_id, revision, payload, content_hash, branding):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            matched = session.execute(update(TradeDocument).where(
                TradeDocument.id == document_id, TradeDocument.user_id == self.user_id,
                TradeDocument.doc_kind == self.document_type, TradeDocument.revision == revision,
                TradeDocument.status.in_(("ready", "needs_input")),
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

    def reserve_document_number(self, proposal_id, revision, content_hash):
        """최종 발급 시점의 번호를 문서별로 확보하고 렌더 실패 재시도에 재사용한다."""
        with user_lock(self.database, self.user_id), self.database.session() as session:
            # PostgreSQL에서는 사용자 행 잠금으로 같은 사용자의 동시 발급 번호를 직렬화한다.
            session.scalar(select(User.id).where(User.id == self.user_id).with_for_update())
            proposal = self._owned(session, proposal_id)
            self._check(proposal, revision, content_hash)
            if proposal.status != "pending":
                raise DocumentError("PROPOSAL_CONFLICT", "현재 대기 중인 검토 제안을 다시 확인하세요")
            document = session.scalar(select(TradeDocument).where(
                TradeDocument.id == proposal.document_id, TradeDocument.user_id == self.user_id,
                TradeDocument.doc_kind == self.document_type,
            ).with_for_update())
            if document is None or document.revision != revision or document.status != "ready":
                raise DocumentError("REVISION_CONFLICT", "최신 문서를 다시 확인하세요")
            prefix = f"{self.document_type}-"
            reserved = str((document.draft or {}).get("_issue_number_reservation") or "")
            if re.fullmatch(rf"{re.escape(prefix)}\d{{8}}-\d+", reserved):
                return reserved

            numbers = []
            rows = session.scalars(select(TradeDocument).where(
                TradeDocument.user_id == self.user_id, TradeDocument.doc_kind == self.document_type,
            )).all()
            for row in rows:
                draft = row.draft or {}
                if row.status == "issued":
                    numbers.append(draft.get("document_number"))
                numbers.append(draft.get("_issue_number_reservation"))
            approved_versions = session.scalars(select(TradeDocumentVersion.payload).join(
                TradeProposal, and_(TradeProposal.document_id == TradeDocumentVersion.document_id,
                                   TradeProposal.revision == TradeDocumentVersion.revision),
            ).join(TradeDocument, TradeDocument.id == TradeDocumentVersion.document_id).where(
                TradeProposal.user_id == self.user_id, TradeDocument.user_id == self.user_id,
                TradeDocument.doc_kind == self.document_type, TradeProposal.status == "approved",
            )).all()
            numbers.extend((payload or {}).get("document_number") for payload in approved_versions)
            sequences = [int(match.group(1)) for value in numbers if value
                         for match in [re.fullmatch(rf"{re.escape(prefix)}\d{{8}}-(\d+)", str(value).strip())]
                         if match]
            today = datetime.now(timezone(timedelta(hours=9))).date()
            number = f"{self.document_type}-{today:%Y%m%d}-{max(sequences, default=0) + 1:03d}"
            document.draft = {**document.draft, "_issue_number_reservation": number}
            session.flush()
            return number

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

    def _store_issued(self, proposal_id: str, file: RenderedFile) -> tuple[str, str, int]:
        """렌더된 한 형식을 결정적 key에 저장한다. `(object_key, sha256, 크기)`를 돌려준다.

        이미 key가 있으면 같은 bytes로 확인된 경우만 재사용하고 다른 bytes면 실패시킨다
        (계약 16.3절). Storage 호출 실패는 503으로 나가 승인을 중단시킨다.
        """
        digest = sha256(file.content).hexdigest()
        key = issued_object_key(self.user_id, proposal_id, file.file_format, digest)
        try:
            existing = self.storage.download(key)
        except StorageError as error:
            if error.code != "object_not_found":
                raise _image_document_error(error) from error
            existing = None
        if existing is not None:
            if sha256(existing).hexdigest() != digest:
                raise DocumentError("ARTIFACT_CORRUPTED",
                                    "같은 발급 위치에 다른 내용이 저장돼 있습니다. 관리자에게 문의해 주세요.", 503)
            return key, digest, len(file.content)  # 같은 bytes는 새로 올리지 않고 재사용한다.
        try:
            self.storage.upload(key, file.content, file.media_type)
        except StorageError as error:
            if error.code != "object_exists":
                raise _image_document_error(error) from error
            try:
                existing = self.storage.download(key)
            except StorageError as read_error:
                raise _image_document_error(read_error) from read_error
            if sha256(existing).hexdigest() != digest:
                raise DocumentError("ARTIFACT_CORRUPTED", "동시에 저장된 발급 파일의 내용이 다릅니다.", 503)
        return key, digest, len(file.content)

    def approve(self, proposal_id, revision, content_hash, files, issued_document):
        if self.storage is None:
            raise DocumentError("STORAGE_NOT_CONFIGURED",
                                "SUPABASE_URL·SUPABASE_SECRET_KEY가 설정되지 않아 발급 파일을 저장할 수 없습니다.", 503)
        with user_lock(self.database, self.user_id), self.database.session() as session:
            row = self._owned(session, proposal_id)
            self._check(row, revision, content_hash)
            if row.status == "approved":
                # 동시 승인·응답 유실 재시도: Storage를 다시 건드리지 않고 기존 파일을 돌려준다.
                return self._view(session, row)
            keys = [issued_object_key(self.user_id, proposal_id, file.file_format,
                                      sha256(file.content).hexdigest()) for file in files]
            for key in sorted(keys):
                lock_object(session, key)
            # ① 요청한 모든 형식을 먼저 Storage에 저장한다. 중간에 실패하면 아래 SQL은
            #    실행되지 않아 문서는 ready, 제안은 pending으로 남는다.
            stored = [self._store_issued(proposal_id, file) for file in files]
            # ② 모든 형식이 저장된 뒤에만 SQL 트랜잭션으로 revision·제안·파일 참조를 확정한다.
            current = session.scalar(select(TradeDocument).where(
                TradeDocument.id == row.document_id, TradeDocument.user_id == self.user_id,
                TradeDocument.doc_kind == self.document_type, TradeDocument.revision == revision,
                TradeDocument.status == "ready",
            ).with_for_update())
            if current is None:
                session.refresh(row)
                if row.status == "approved":
                    return self._view(session, row)
                raise DocumentError("REVISION_CONFLICT", "최신 문서를 다시 확인하세요")
            reservation = (current.draft or {}).get("_issue_number_reservation")
            if not reservation or issued_document.get("document_number") != reservation:
                raise DocumentError("PROPOSAL_CONFLICT", "승인할 문서번호를 다시 확인하세요")
            final_document = {**deepcopy(issued_document), "status": "issued",
                              "trade_doc_id": current.id, "doc_no": current.doc_no,
                              "doc_kind": current.doc_kind, "document_type": current.doc_kind,
                              "revision": current.revision}
            final_document.pop("_issue_number_reservation", None)
            matched = session.execute(update(TradeDocument).where(
                TradeDocument.id == row.document_id, TradeDocument.user_id == self.user_id,
                TradeDocument.doc_kind == self.document_type, TradeDocument.revision == revision,
                TradeDocument.status == "ready",
            ).values(status="issued", draft=final_document)).rowcount
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
            version = session.get(TradeDocumentVersion, (row.document_id, revision))
            if version is not None:
                version.payload = deepcopy(final_document)
            session.add_all([TradeArtifact(
                id=uuid4().hex, user_id=self.user_id, proposal_id=row.id, file_format=file.file_format,
                filename=file.filename, media_type=file.media_type, content=None,
                content_hash=digest, object_key=key, size_bytes=size)
                for file, (key, digest, size) in zip(files, stored, strict=True)])
            session.flush()
            session.refresh(row)
            return self._view(session, row)

    def file(self, file_id):
        with self.database.session() as session:
            row = session.scalar(select(TradeArtifact).join(TradeProposal).where(
                TradeArtifact.id == file_id, TradeArtifact.user_id == self.user_id,
                TradeProposal.user_id == self.user_id, TradeProposal.status == "approved"))
            if row is None:
                raise DocumentError("FILE_NOT_FOUND", "확정된 파일을 찾을 수 없습니다", 404)
            record = {"filename": row.filename, "media_type": row.media_type,
                      "content_hash": row.content_hash, "object_key": row.object_key,
                      "content": row.content}
        if record["object_key"] is None:
            record.pop("object_key")  # backfill 전 옛 행: 보존된 DB bytes로 내려받는다(10절 이전 행).
            return record
        if self.storage is None:
            raise DocumentError("STORAGE_NOT_CONFIGURED",
                                "SUPABASE_URL·SUPABASE_SECRET_KEY가 설정되지 않아 발급 파일을 읽을 수 없습니다.", 503)
        try:
            content = self.storage.download(record["object_key"])
        except StorageError as error:
            raise _image_document_error(error) from error
        if sha256(content).hexdigest() != record["content_hash"]:
            # 읽을 때 해시를 확인한다(계약 16.3절). 손상·조작을 성공으로 돌려주지 않는다.
            raise DocumentError("ARTIFACT_CORRUPTED",
                                "저장된 발급 파일이 기록과 일치하지 않습니다. 관리자에게 문의해 주세요.", 503)
        record.pop("object_key")
        return {**record, "content": content}
