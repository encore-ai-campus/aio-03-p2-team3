"""문서 출처 연결(CONTRACT 16.3절, 계획 8절): 파일 ID 목록·기대 revision 검증 후 새 revision로 확정.

`PUT /api/trade/{kind}/{document_id}/sources`. 소유자·문서 종류·개수·파일 존재·소유를 검사하고,
성공하면 문서를 새 revision로 만들어 대기 검토를 무효화하고 과거 revision의 연결 행은 보존한다.
"""
from copy import deepcopy

from pydantic import Field
from sqlalchemy import select, update

from app.db.models import FileAsset, TradeDocument, TradeDocumentSource, TradeDocumentVersion, TradeProposal, utcnow
from app.files.service import metadata_view
from app.files.validation import MAX_SOURCES_PER_DOCUMENT
from app.services.locks import user_lock
from app.trade.common.models import DocumentError, InputModel


class SourcesLink(InputModel):
    revision: int = Field(ge=1, strict=True)
    file_ids: list[int] = Field(default_factory=list, max_length=MAX_SOURCES_PER_DOCUMENT)


def link_document_sources(database, user_id: int, kind: str, document_id: int,
                          revision: int, file_ids: list[int]) -> dict:
    with user_lock(database, user_id), database.session() as session:
        row = session.scalar(select(TradeDocument).where(
            TradeDocument.id == document_id, TradeDocument.user_id == user_id,
            TradeDocument.doc_kind == kind))
        if row is None:
            raise DocumentError("DOCUMENT_NOT_FOUND", "문서를 찾을 수 없습니다", 404)
        if row.revision != revision or row.status in ("sent", "sending"):
            raise DocumentError("REVISION_CONFLICT", "최신 문서를 다시 확인하세요")
        if len(set(file_ids)) != len(file_ids):
            raise DocumentError("DUPLICATE_FILE_IDS", "같은 파일이 두 번 들어 있습니다", 422)
        assets = []
        for file_id in file_ids:
            asset = session.get(FileAsset, file_id)
            if asset is None or asset.user_id != user_id:
                raise DocumentError("FILE_NOT_OWNED",
                                    "문서에 연결할 파일을 찾을 수 없습니다. 본인이 올린 파일인지 확인하세요", 422)
            assets.append(asset)
        new_revision = revision + 1
        payload = {**deepcopy(row.draft), "revision": new_revision}
        claimed = session.execute(update(TradeDocument).where(
            TradeDocument.id == document_id, TradeDocument.user_id == user_id,
            TradeDocument.doc_kind == kind, TradeDocument.revision == revision,
            TradeDocument.status.not_in(("sent", "sending")),
        ).values(draft=payload, revision=new_revision)).rowcount
        if claimed != 1:
            raise DocumentError("REVISION_CONFLICT", "최신 문서를 다시 확인하세요")
        session.add(TradeDocumentVersion(document_id=document_id, user_id=user_id,
                                          revision=new_revision, payload=deepcopy(payload)))
        # 대기 검토를 무효화한다(기존 문서 수정과 같은 규칙, CONTRACT 16절).
        session.execute(update(TradeProposal).where(
            TradeProposal.document_id == document_id, TradeProposal.user_id == user_id,
            TradeProposal.status == "pending",
        ).values(status="superseded", decided_at=utcnow()))
        for asset in assets:
            session.add(TradeDocumentSource(user_id=user_id, trade_document_id=document_id,
                                            doc_kind=kind, revision=new_revision,
                                            file_id=asset.id, origin="upload"))
        session.flush()
        return {"document_id": document_id, "revision": new_revision,
                "files": [{k: v for k, v in metadata_view(asset).items() if k != "created_at"}
                          for asset in assets]}
