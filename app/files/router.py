"""비공개 Storage 첨부 API — Bearer 전용 경로(CONTRACT 9.1·16.3절, 계획 8절).

- `POST /api/files`: multipart로 파일 한 개. 크기·시그니처 검증 후 업로드와 메타데이터 확정.
- `GET /api/files/{file_id}`: 메타데이터. `GET /api/files/{file_id}/download`: bytes(no-store).
- `DELETE /api/files/{file_id}`: 다른 기록에 쓰이지 않은 파일만(참조 중이면 409).
문서 출처 연결 `PUT /api/trade/{kind}/{document_id}/sources`는 `app/trade/common/router.py`가 싣는다.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.auth.supabase import bearer_user_id
from app.files import service
from app.files.service import FileError
from app.files.validation import MAX_ATTACHMENT_BYTES, safe_disposition

router = APIRouter(prefix="/api/files", tags=["files"])

READ_CHUNK_BYTES = 64 * 1024


def require_storage(request: Request):
    storage = request.app.state.storage
    if storage is None:
        raise FileError(503, "storage_not_configured",
                        "SUPABASE_URL·SUPABASE_SECRET_KEY가 설정되지 않아 파일 저장을 쓸 수 없습니다.")
    return storage


async def _read_limited(file: UploadFile) -> bytes | None:
    """한도까지만 읽는다. 한도를 넘으면 나머지를 읽지 않고 None을 돌려준다(413 처리)."""
    chunks, total = [], 0
    while True:
        chunk = await file.read(READ_CHUNK_BYTES)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_ATTACHMENT_BYTES:
            return None


@router.post("")
async def upload_file(request: Request, user_id: int = Depends(bearer_user_id)):
    storage = require_storage(request)
    form = await request.form()
    files = [value for _, value in form.multi_items() if isinstance(value, UploadFile)]
    if len(files) != 1:
        raise FileError(422, "one_file_per_request",
                        "파일 한 개씩 multipart로 보내 주세요.")
    data = await _read_limited(files[0])
    if data is None:
        raise FileError(413, "file_too_large",
                        f"파일이 너무 큽니다(최대 {MAX_ATTACHMENT_BYTES // (1024 * 1024)}MiB).")
    return await run_in_threadpool(service.upload_attachment, request.app.state.database, storage,
                                   user_id, files[0].filename or "", data)


@router.get("/{file_id}")
def file_metadata(file_id: int, request: Request, user_id: int = Depends(bearer_user_id)):
    return service.get_file(request.app.state.database, user_id, file_id)


@router.get("/{file_id}/download")
def file_download(file_id: int, request: Request, user_id: int = Depends(bearer_user_id)):
    storage = require_storage(request)
    file = service.download_file(request.app.state.database, storage, user_id, file_id)
    return Response(content=file["content"], media_type=file["content_type"], headers={
        "Content-Disposition": safe_disposition(file["filename"]),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    })


@router.delete("/{file_id}", status_code=204)
def file_delete(file_id: int, request: Request, user_id: int = Depends(bearer_user_id)):
    storage = require_storage(request)
    service.delete_file(request.app.state.database, storage, user_id, file_id)
    return Response(status_code=204)
