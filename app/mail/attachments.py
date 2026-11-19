"""수집된 Gmail 메시지의 첨부 목록과 인증된 원본."""
from base64 import b64decode
from binascii import Error
from urllib.parse import quote

from sqlalchemy import select

from app.clients.gmail import GoogleError, MessageNotFound, TokenExpired
from app.db.models import ThreadMessage
from app.services.auth import ConfigMissing, get_access_token
from app.mail.errors import MailError

MAX_BYTES = 20 * 1024 * 1024


def _parts(part, path="0"):
    if part.get("filename"):
        yield path, part
    for index, child in enumerate(part.get("parts", [])):
        yield from _parts(child, f"{path}.{index}")


def _source(database, access, actor_id, thread_id, message_id):
    with database.session() as session:
        owned = session.scalar(select(ThreadMessage.id).where(
            ThreadMessage.user_id == actor_id, ThreadMessage.thread_id == thread_id,
            ThreadMessage.gmail_message_id == message_id,
        ).limit(1))
    if owned is None:
        raise MailError(404, "mail_attachment_source_missing", "원본 메일을 찾을 수 없습니다.")
    if access is None:
        raise MailError(409, "gmail_not_connected", "Gmail 계정을 연결해 주세요.")
    try:
        gmail = access.google.gmail(get_access_token(access, actor_id))
        raw = access.google.get_message(gmail, message_id)
    except MessageNotFound as error:
        raise MailError(404, "mail_attachment_source_missing", "Gmail 원본을 찾을 수 없습니다.") from error
    except (TokenExpired, ConfigMissing) as error:
        raise MailError(409, "gmail_not_connected", "Gmail 계정을 다시 연결해 주세요.") from error
    except GoogleError as error:
        raise MailError(502, "mail_attachment_unavailable", "Gmail 첨부를 읽을 수 없습니다.") from error
    if raw.get("id") != message_id or raw.get("threadId") != thread_id:
        raise MailError(404, "mail_attachment_source_missing", "원본 메일이 일치하지 않습니다.")
    return gmail, dict(_parts(raw.get("payload", {})))


def list_files(database, access, actor_id, thread_id, message_id):
    _, parts = _source(database, access, actor_id, thread_id, message_id)
    prefix = f"/api/mail/threads/{quote(thread_id, safe='')}/messages/{quote(message_id, safe='')}/attachments"
    return {"mail_attachments": [
        {"part_id": key, "filename": part["filename"], "media_type": part.get("mimeType"),
         "size": part.get("body", {}).get("size"), "download_url": f"{prefix}/{key}"}
        for key, part in parts.items()
    ]}


def read_file(database, access, actor_id, thread_id, message_id, part_id):
    gmail, parts = _source(database, access, actor_id, thread_id, message_id)
    part = parts.get(part_id)
    if part is None:
        raise MailError(404, "mail_attachment_not_found", "첨부를 찾을 수 없습니다.")
    body = part.get("body", {})
    size = body.get("size", 0)
    if size > MAX_BYTES:
        raise MailError(413, "mail_attachment_too_large", "20MB를 초과하는 첨부는 Gmail에서 열어 주세요.")
    try:
        attachment_id = body.get("attachmentId")
        encoded = access.google.get_attachment(gmail, message_id, attachment_id) if attachment_id else body.get("data")
        if encoded is None and size == 0:
            encoded = ""
        if encoded is None or len(encoded) > ((MAX_BYTES + 2) // 3) * 4:
            raise ValueError("invalid attachment length")
        content = b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        if len(content) != size or len(content) > MAX_BYTES:
            raise ValueError("attachment size mismatch")
    except (Error, GoogleError, ValueError) as error:
        raise MailError(502, "mail_attachment_unavailable", "Gmail 첨부를 읽을 수 없습니다.") from error
    return content, part["filename"]
