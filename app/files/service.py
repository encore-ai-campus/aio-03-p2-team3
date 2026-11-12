"""첨부 파일 업무(CONTRACT 16.3절, 계획 8절): 업로드 검증 → Storage 저장 → file_assets 확정.

- 업로드 성공 뒤 SQL 실패는 미참조 객체를 남길 수 있다. 요청 실패 처리에서 객체를 무조건 지우지
  않고 `app.files.cleanup` 수동 명령으로 재확인 뒤 정리한다(별도 크론·큐 없음).
- 삭제는 기록(file_assets 행)을 먼저 지우고 객체를 지운다. 객체 삭제 실패로 남은 bytes는
  미참조 객체가 되어 같은 정리 명령의 대상이다(거꾸로 하면 기록만 남아 다운로드가 깨진다).
- 서버 비밀 키는 Storage 정책을 우회하므로 모든 읽기·삭제에서 소유자를 먼저 확인한다.
"""
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError

from app.db.models import CompanyBranding, FileAsset, TradeDocumentSource, TradeProposal
from app.files.storage import StorageClient, StorageError
from app.files.validation import MAX_ATTACHMENT_BYTES, detect_content_type, extension_content_type
from app.services.locks import user_lock


class FileError(Exception):
    """첨부 API 실패. `app/main.py`가 `{"error": …}` JSON으로 바꾼다."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def attachments_object_key(user_id: int) -> str:
    """object key는 서버가 만든다. 원래 파일명·사용자 입력은 경로에 쓰지 않는다."""
    return f"{user_id}/attachments/{uuid4().hex}"


def metadata_view(row: FileAsset) -> dict:
    return {"file_id": row.id, "filename": row.original_filename, "content_type": row.content_type,
            "size_bytes": row.size_bytes, "sha256": row.sha256,
            "created_at": row.created_at.isoformat()}


def _owned(session, user_id: int, file_id: int) -> FileAsset | None:
    row = session.get(FileAsset, file_id)
    return row if row is not None and row.user_id == user_id else None


def upload_attachment(database, storage: StorageClient, user_id: int,
                      filename: str, data: bytes) -> dict:
    if not filename.strip():
        raise FileError(422, "filename_required", "파일 이름이 비었습니다.")
    if not data:
        raise FileError(422, "empty_file", "빈 파일은 저장할 수 없습니다.")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise FileError(413, "file_too_large",
                        f"파일이 너무 큽니다(최대 {MAX_ATTACHMENT_BYTES // (1024 * 1024)}MiB).")
    expected = extension_content_type(filename)
    if expected is None:
        raise FileError(415, "unsupported_media_type",
                        "허용하지 않는 형식입니다. PDF·XLSX·TXT·PNG·JPEG만 저장할 수 있습니다.")
    content_type = detect_content_type(data)
    if content_type is None:
        raise FileError(415, "unsupported_media_type",
                        "파일 내용이 허용하는 형식(PDF·XLSX·TXT·PNG·JPEG)과 맞지 않습니다.")
    if content_type != expected:
        # 확장자·클라이언트 Content-Type만 믿지 않는다: 시그니처로 확인한 실제 형식과 다르면 거부한다.
        raise FileError(415, "signature_mismatch",
                        "파일 내용이 파일 이름이 가리키는 형식과 일치하지 않습니다.")
    object_key = attachments_object_key(user_id)
    try:
        storage.upload(object_key, data, content_type)
    except StorageError as error:
        raise FileError(503, "storage_unavailable", error.message) from error
    # Storage 저장이 성공한 뒤에만 메타데이터를 확정한다. 이 SQL이 실패하면 위 객체는
    # 미참조로 남는다(지우지 않는다. 정리는 cleanup 명령).
    with database.session() as session:
        row = FileAsset(user_id=user_id, original_filename=filename, content_type=content_type,
                        size_bytes=len(data), sha256=sha256(data).hexdigest(), object_key=object_key)
        session.add(row)
        session.flush()
        view = metadata_view(row)
    view.pop("created_at")  # POST 응답 계약(CONTRACT 16.3절): {file_id, filename, content_type, size_bytes, sha256}
    return view


def get_file(database, user_id: int, file_id: int) -> dict:
    with database.session() as session:
        row = _owned(session, user_id, file_id)
        if row is None:
            raise FileError(404, "file_not_found", "파일을 찾을 수 없습니다.")
        return metadata_view(row)


def download_file(database, storage: StorageClient, user_id: int, file_id: int) -> dict:
    with database.session() as session:
        row = _owned(session, user_id, file_id)
        if row is None:
            raise FileError(404, "file_not_found", "파일을 찾을 수 없습니다.")
        filename, content_type, digest, object_key = (
            row.original_filename, row.content_type, row.sha256, row.object_key)
    try:
        content = storage.download(object_key)
    except StorageError as error:
        raise FileError(503, "storage_unavailable", error.message) from error
    if sha256(content).hexdigest() != digest:
        # 읽을 때 해시를 확인한다(CONTRACT 16.3). 손상·조작을 성공으로 돌려주지 않는다.
        raise FileError(503, "object_corrupted",
                        "저장된 파일이 기록과 일치하지 않습니다. 관리자에게 문의해 주세요.")
    return {"filename": filename, "content_type": content_type, "content": content}


def _file_in_use(session, file_id: int) -> bool:
    """문서 출처·회사 설정(로고/직인)·검토 제안이 가리키는 파일은 사용 중이다(계획 9절)."""
    return any(session.scalar(select(column).where(condition).limit(1)) is not None for column, condition in (
        (TradeDocumentSource.id, TradeDocumentSource.file_id == file_id),
        (CompanyBranding.user_id, or_(CompanyBranding.logo_file_id == file_id,
                                      CompanyBranding.seal_file_id == file_id)),
        (TradeProposal.id, or_(TradeProposal.logo_file_id == file_id,
                               TradeProposal.seal_file_id == file_id)),
    ))


def delete_file(database, storage: StorageClient, user_id: int, file_id: int) -> None:
    with user_lock(database, user_id), database.session() as session:
        row = _owned(session, user_id, file_id)
        if row is None:
            raise FileError(404, "file_not_found", "파일을 찾을 수 없습니다.")
        object_key = row.object_key
        if _file_in_use(session, file_id):
            raise FileError(409, "file_in_use",
                            "다른 기록에서 참조 중인 파일은 삭제할 수 없습니다. 참조를 먼저 바꿔 주세요.")
        try:
            claimed = session.execute(delete(FileAsset).where(
                FileAsset.id == file_id, FileAsset.user_id == user_id)).rowcount
        except IntegrityError as error:
            # 프로세스 밖에서 동시에 참조가 생기면 외래 키가 삭제를 막는다(기록은 그대로).
            raise FileError(409, "file_in_use",
                            "다른 기록에서 참조 중인 파일은 삭제할 수 없습니다.") from error
        if claimed != 1:
            raise FileError(404, "file_not_found", "파일을 찾을 수 없습니다.")
    try:
        storage.delete(object_key)
    except StorageError as error:
        # 기록은 지워졌고 객체만 남는다. 미참조 객체이므로 cleanup 명령이 정리한다.
        raise FileError(503, "storage_cleanup_failed",
                        "파일 기록은 지웠지만 저장소 정리에 실패했습니다. 남은 객체는 관리 명령으로 정리됩니다.") from error
