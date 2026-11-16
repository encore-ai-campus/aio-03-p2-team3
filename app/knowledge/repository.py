"""소유자별 수집 기록·임대와 pgvector의 원자적 교체. 외부 API를 호출하지 않는다."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, delete, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base, Created, FileAsset, JSON_VALUE, UTCDateTime, utcnow
from app.knowledge.schemas import (
    ACTIVE_STATUSES, CHUNK_VERSION, ChildChunk, KnowledgeError, ModelProfile,
    ParentChunk, ReviewRequest,
)

LEASE_SECONDS = 3600


class KnowledgeDocument(Base, Created):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("user_id", "sha256", name="uq_knowledge_owner_hash"),
        UniqueConstraint("id", "user_id", name="uq_knowledge_document_owner"),
        CheckConstraint("status IN ('queued','extracting','needs_review','chunking','embedding','ready','failed')",
                        name="ck_knowledge_status"),
        Index("ix_knowledge_queue", "status", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("file_assets.id", ondelete="RESTRICT"), index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    attempt_id: Mapped[str] = mapped_column(String(36))
    lease_until: Mapped[object | None] = mapped_column(UTCDateTime())
    revision: Mapped[int] = mapped_column(Integer, default=0)
    raw_pages: Mapped[list] = mapped_column(JSON_VALUE, default=list)
    pages: Mapped[list] = mapped_column(JSON_VALUE, default=list)
    approved: Mapped[bool] = mapped_column(default=False)
    warnings: Mapped[list] = mapped_column(JSON_VALUE, default=list)
    profile: Mapped[dict] = mapped_column(JSON_VALUE, default=dict)
    published_attempt_id: Mapped[str | None] = mapped_column(String(36))
    published_profile: Mapped[dict] = mapped_column(JSON_VALUE, default=dict)
    published_pages: Mapped[list] = mapped_column(JSON_VALUE, default=list)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_stage: Mapped[str | None] = mapped_column(String(24))
    updated_at: Mapped[object] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class KnowledgeParent(Base):
    __tablename__ = "knowledge_parents"
    __table_args__ = (
        ForeignKeyConstraint(["document_id", "user_id"],
                             ["knowledge_documents.id", "knowledge_documents.user_id"], ondelete="CASCADE"),
        UniqueConstraint("id", "document_id", "user_id", "attempt_id", name="uq_knowledge_parent_scope"),
        UniqueConstraint("document_id", "attempt_id", "ordinal", name="uq_knowledge_parent_order"),
        Index("ix_knowledge_parent_document_owner", "document_id", "user_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(36))
    user_id: Mapped[int] = mapped_column(Integer)
    attempt_id: Mapped[str] = mapped_column(String(36))
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)
    sources: Mapped[list] = mapped_column(JSON_VALUE)


class KnowledgeChild(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        ForeignKeyConstraint(["parent_id", "document_id", "user_id", "attempt_id"],
                             ["knowledge_parents.id", "knowledge_parents.document_id",
                              "knowledge_parents.user_id", "knowledge_parents.attempt_id"], ondelete="CASCADE"),
        UniqueConstraint("document_id", "attempt_id", "ordinal", name="uq_knowledge_child_order"),
        CheckConstraint("dimensions > 0 AND vector_dims(embedding) = dimensions", name="ck_knowledge_vector_dims"),
        CheckConstraint('"start" >= 0 AND "end" > "start" AND char_length(text) = "end" - "start"',
                        name="ck_knowledge_child_span"),
        Index("ix_knowledge_child_parent_scope", "parent_id", "document_id", "user_id", "attempt_id"),
        Index("ix_knowledge_child_owner_profile", "user_id", "profile_id", "document_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    parent_id: Mapped[str] = mapped_column(String(36))
    document_id: Mapped[str] = mapped_column(String(36))
    user_id: Mapped[int] = mapped_column(Integer)
    attempt_id: Mapped[str] = mapped_column(String(36))
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(Vector())
    dimensions: Mapped[int] = mapped_column(Integer)
    profile_id: Mapped[str] = mapped_column(String(64))


def _owned(session, owner, document_id, *, lock=False):
    query = select(KnowledgeDocument).where(KnowledgeDocument.id == document_id,
                                            KnowledgeDocument.user_id == owner)
    row = session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise KnowledgeError("document_not_found", "문서를 찾을 수 없습니다.", 404)
    return row


def _summary(session, row):
    file = session.get(FileAsset, row.file_id)
    return {"id": row.id, "filename": file.original_filename, "file_id": file.id,
            "content_type": file.content_type, "size_bytes": file.size_bytes, "sha256": row.sha256,
            "status": row.status, "attempt_id": row.attempt_id, "revision": row.revision,
            "error_code": row.error_code, "error_stage": row.error_stage,
            "published_attempt_id": row.published_attempt_id, "profile": row.profile,
            "published_profile": row.published_profile,
            "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}


class SqlRepository:
    def __init__(self, database):
        self.database = database

    @contextmanager
    def _session(self):
        try:
            with self.database.session() as session:
                yield session
        except SQLAlchemyError:
            # SQL 예외에는 원문 매개변수가 포함될 수 있다. HTTP/로그로 넘기지 않는다.
            raise KnowledgeError("knowledge_database_unavailable", "문서 저장소를 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.", 503) from None

    def duplicate(self, owner: int, digest: str) -> dict | None:
        with self._session() as session:
            row = session.scalar(select(KnowledgeDocument).where(
                KnowledgeDocument.user_id == owner, KnowledgeDocument.sha256 == digest))
            return _summary(session, row) if row else None

    def create(self, owner: int, metadata: dict) -> dict:
        try:
            with self.database.session() as session:
                file = FileAsset(user_id=owner, **metadata)
                session.add(file)
                session.flush()
                row = KnowledgeDocument(id=str(uuid4()), user_id=owner, file_id=file.id,
                                        sha256=file.sha256, attempt_id=str(uuid4()))
                session.add(row)
                session.flush()
                return _summary(session, row)
        except IntegrityError:
            # 동시 업로드도 문서/큐는 하나다. SQL에서 지지 못한 객체는 기존 수동 정리 대상이다.
            existing = self.duplicate(owner, metadata["sha256"])
            if existing is None:
                raise KnowledgeError("knowledge_database_unavailable", "문서 기록을 저장하지 못했습니다.", 503) from None
            return {**existing, "duplicate": True}
        except SQLAlchemyError:
            raise KnowledgeError("knowledge_database_unavailable", "문서 기록을 저장하지 못했습니다.", 503) from None

    def list(self, owner: int, *, offset: int = 0) -> list[dict]:
        with self._session() as session:
            rows = session.scalars(select(KnowledgeDocument).where(KnowledgeDocument.user_id == owner)
                                   .order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id)
                                   .offset(offset).limit(20))
            return [_summary(session, row) for row in rows]

    def read(self, owner: int, document_id: str) -> dict:
        with self._session() as session:
            row = _owned(session, owner, document_id)
            result = _summary(session, row)
            result.update(raw_pages=row.raw_pages, pages=row.pages, approved=row.approved,
                          warnings=row.warnings, published_pages=row.published_pages)
            for name, model in (("parent_count", KnowledgeParent), ("child_count", KnowledgeChild)):
                result[name] = session.scalar(select(func.count()).select_from(model).where(
                    model.document_id == row.id, model.attempt_id == row.published_attempt_id))
            return result

    def chunks(self, owner: int, document_id: str, offset: int = 0) -> dict:
        with self._session() as session:
            row = _owned(session, owner, document_id)
            children = list(session.scalars(select(KnowledgeChild).where(
                KnowledgeChild.document_id == row.id, KnowledgeChild.user_id == owner,
                KnowledgeChild.attempt_id == row.published_attempt_id)
                .order_by(KnowledgeChild.ordinal).offset(offset).limit(50)))
            parents = list(session.scalars(select(KnowledgeParent).where(
                KnowledgeParent.id.in_({child.parent_id for child in children}),
                KnowledgeParent.user_id == owner)))
            return {"attempt_id": row.published_attempt_id,
                    "children": [{"id": c.id, "parent_id": c.parent_id, "ordinal": c.ordinal,
                                  "text": c.text, "start": c.start, "end": c.end,
                                  "dimensions": c.dimensions, "profile_id": c.profile_id} for c in children],
                    "parents": [{"id": p.id, "ordinal": p.ordinal, "text": p.text,
                                 "start": p.start, "end": p.end, "sources": p.sources} for p in parents]}

    def original(self, owner: int, document_id: str) -> dict:
        with self._session() as session:
            row = _owned(session, owner, document_id)
            file = session.get(FileAsset, row.file_id)
            return {"object_key": file.object_key, "sha256": file.sha256,
                    "filename": file.original_filename, "content_type": file.content_type}

    def retry(self, owner: int, document_id: str, attempt_id: str) -> dict:
        with self._session() as session:
            row = _owned(session, owner, document_id, lock=True)
            if row.attempt_id != attempt_id or row.status in ACTIVE_STATUSES:
                raise KnowledgeError("attempt_conflict", "처리 상태가 바뀌었습니다. 새로고침해 주세요.", 409)
            row.attempt_id, row.status = str(uuid4()), "queued"
            row.raw_pages, row.pages, row.warnings, row.profile = [], [], [], {}
            row.approved, row.lease_until = False, None
            row.error_code, row.error_stage = None, None
            row.revision += 1
            session.flush()
            return _summary(session, row)

    def review(self, owner: int, document_id: str, request: ReviewRequest) -> dict:
        with self._session() as session:
            row = _owned(session, owner, document_id, lock=True)
            if (row.attempt_id != request.attempt_id or row.revision != request.revision
                    or row.status in ACTIVE_STATUSES or not row.pages):
                raise KnowledgeError("revision_conflict", "원문 또는 처리 상태가 바뀌었습니다. 다시 조회해 주세요.", 409)
            if [p.number for p in request.pages] != [p["number"] for p in row.pages]:
                raise KnowledgeError("page_mismatch", "모든 페이지를 원래 순서대로 보내 주세요.")
            if row.status != "needs_review":
                row.attempt_id, row.profile = str(uuid4()), {}
            row.pages = [{**old, "text": edit.text, "blank": not bool(edit.text.strip()),
                          "complete": True, "uncertain": []} for old, edit in zip(row.pages, request.pages)]
            row.revision += 1
            row.approved = request.confirm
            if request.confirm:
                row.warnings = []  # 원본 대조·확정으로 해결한 경고는 미해결 안내로 남기지 않는다.
            row.status = "queued" if request.confirm else "needs_review"
            row.lease_until, row.error_code, row.error_stage = None, None, None
            session.flush()
            return _summary(session, row)

    def expire(self) -> None:
        with self._session() as session:
            session.execute(update(KnowledgeDocument).where(
                KnowledgeDocument.status.in_(ACTIVE_STATUSES - {"queued"}),
                KnowledgeDocument.lease_until < utcnow()).values(
                    status="failed", error_code="processing_interrupted", error_stage="processing",
                    lease_until=None))

    def claim(self) -> dict | None:
        with self._session() as session:
            row = session.scalar(select(KnowledgeDocument).where(KnowledgeDocument.status == "queued")
                                 .order_by(KnowledgeDocument.created_at).with_for_update(skip_locked=True).limit(1))
            if row is None:
                return None
            row.status = "chunking" if row.approved else "extracting"
            row.lease_until = utcnow() + timedelta(seconds=LEASE_SECONDS)
            session.flush()
            return {"id": row.id, "user_id": row.user_id, "attempt_id": row.attempt_id,
                    "approved": row.approved, "pages": row.pages, "profile": row.profile}

    def update_attempt(self, document_id: str, attempt_id: str, **values) -> bool:
        allowed = {"status", "raw_pages", "pages", "approved", "warnings", "profile", "error_code", "error_stage"}
        if set(values) - allowed:
            raise ValueError("허용하지 않는 처리 갱신")
        if values.get("status") in {"failed", "needs_review"}:
            values["lease_until"] = None
        with self._session() as session:
            changed = session.execute(update(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id, KnowledgeDocument.attempt_id == attempt_id,
                KnowledgeDocument.status.in_(ACTIVE_STATUSES), KnowledgeDocument.lease_until > utcnow())
                .values(**values)).rowcount
            return changed == 1

    def publish(self, document_id: str, attempt_id: str, parents: list[ParentChunk],
                children: list[ChildChunk], vectors: list[list[float]], profile: ModelProfile) -> bool:
        by_id = {p.id: p for p in parents}
        if (not parents or not children or len(children) != len(vectors)
                or any(c.parent_id not in by_id or by_id[c.parent_id].text[c.start:c.end] != c.text
                       for c in children)):
            raise KnowledgeError("chunk_mismatch", "부모와 자식 청크의 원문 범위가 맞지 않습니다.")
        with self._session() as session:
            row = session.scalar(select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
                                 .with_for_update())
            if (row is None or row.attempt_id != attempt_id or row.status != "embedding"
                    or row.lease_until is None or row.lease_until <= utcnow() or not row.approved):
                return False
            scope = {"document_id": row.id, "user_id": row.user_id, "attempt_id": attempt_id}
            # 전부 검증한 결과만 같은 트랜잭션에서 바꾼다. 실패 시 기존 부모/벡터도 롤백된다.
            session.execute(delete(KnowledgeChild).where(KnowledgeChild.document_id == row.id))
            session.execute(delete(KnowledgeParent).where(KnowledgeParent.document_id == row.id))
            for parent in parents:
                session.add(KnowledgeParent(**scope, **parent.model_dump()))
            session.flush()
            for child, vector in zip(children, vectors):
                session.add(KnowledgeChild(**scope, **child.model_dump(), embedding=vector,
                                           dimensions=profile.dimensions, profile_id=profile.fingerprint))
            row.published_attempt_id = attempt_id
            row.published_profile = {**row.profile, "embedding": profile.model_dump(), "chunking": CHUNK_VERSION}
            row.published_pages = row.pages
            row.status, row.lease_until = "ready", None
            row.error_code, row.error_stage = None, None
            session.flush()
            return True
