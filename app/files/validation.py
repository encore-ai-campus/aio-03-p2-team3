"""첨부 파일 입력 검증(CONTRACT 16.3절 한도). 확장자·클라이언트 Content-Type은 근거로 쓰지 않는다."""
from re import sub
from urllib.parse import quote

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024  # 파일당 5MiB
MAX_SOURCES_PER_DOCUMENT = 5  # 문서당 5개

PDF_TYPE = "application/pdf"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TXT_TYPE = "text/plain; charset=utf-8"
PNG_TYPE = "image/png"
JPEG_TYPE = "image/jpeg"

# 확장자가 주장하는 형식(시그니처 결과와 이 값이 같아야 한다).
EXTENSION_TYPES = {
    ".pdf": PDF_TYPE, ".xlsx": XLSX_TYPE, ".txt": TXT_TYPE,
    ".png": PNG_TYPE, ".jpg": JPEG_TYPE, ".jpeg": JPEG_TYPE,
}


def extension_content_type(filename: str) -> str | None:
    """확장자가 가리키는 허용 형식. 없는 확장자는 허용하지 않는 형식이다(None)."""
    name = filename.rsplit("/", 1)[-1].lower()  # 일부 클라이언트가 경로를 섞어 보내도 확장자만 본다
    for extension, content_type in EXTENSION_TYPES.items():
        if name.endswith(extension):
            return content_type
    return None


def detect_content_type(data: bytes) -> str | None:
    """bytes의 파일 시그니처로 실제 형식을 판별한다. 허용 목록에 없으면 None.

    - PDF: 헤더 `%PDF-`(규격상 처음 1024바이트 안). PNG·JPEG: 고정 매직 바이트.
    - XLSX: OOXML zip(`PK\\x03\\x04`)이면서 `[Content_Types].xml`과 `xl/` 부분이 함께 있는 경우.
    - TXT: 매직 바이트가 없으므로 NUL 바이트 없이 UTF-8로 읽히는 경우만 텍스트로 인정한다.
    """
    if data.startswith(b"%PDF-") or b"%PDF-" in data[:1024]:
        return PDF_TYPE
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG_TYPE
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG_TYPE
    if data.startswith(b"PK\x03\x04") and b"[Content_Types].xml" in data and b"xl/" in data:
        return XLSX_TYPE
    if b"\x00" not in data:
        try:
            data.decode("utf-8")
            return TXT_TYPE
        except UnicodeDecodeError:
            pass
    return None


def safe_disposition(filename: str) -> str:
    """다운로드 Content-Disposition. 경로·제어 문자를 없애고 UTF-8 원본은 filename*로만 실는다."""
    fallback = sub(r"[^A-Za-z0-9._-]", "_", filename).strip("._") or "download"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"
