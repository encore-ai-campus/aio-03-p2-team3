"""공통 무역 원문 입력용 파일 텍스트 추출."""
from pathlib import Path

from app.knowledge.schemas import KnowledgeError, MAX_FILE_BYTES
from app.knowledge.validation import validate_upload

MAX_SOURCE_PAGES = 5
MAX_SOURCE_TEXT_CHARS = 20_000
SUPPORTED_EXTENSIONS = {".pdf", ".xlsx", ".txt", ".png", ".jpg", ".jpeg"}


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp949"):
        try:
            text = data.decode(encoding)
            if "\x00" not in text:
                return text
        except UnicodeDecodeError:
            continue
    raise KnowledgeError("text_encoding_invalid", "TXT 파일은 UTF-8·UTF-16·CP949 문자 인코딩이어야 합니다.")


def extract_source_text(filename: str, data: bytes, renderer, extractor) -> dict:
    extension = Path(filename or "").suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise KnowledgeError("unsupported_format", "PDF·Excel(XLSX)·TXT·PNG·JPG 파일을 지원합니다.", 415)
    if len(data) > MAX_FILE_BYTES:
        raise KnowledgeError("file_too_large", "파일은 20MiB 이하여야 합니다.", 413)

    if extension == ".txt":
        text = _decode_text(data)
        normalized = text.encode("utf-8")
        safe_name, _ = validate_upload(filename, normalized)
        if len(text) > MAX_SOURCE_TEXT_CHARS:
            raise KnowledgeError("source_text_limit", "원문이 20,000자를 넘습니다. 파일을 나누어 읽어 주세요.")
        return {"filename": safe_name, "text": text, "page_count": 1, "review_required": False}

    safe_name, _ = validate_upload(filename, data)
    rendered = renderer.render(data, safe_name, max_pages=MAX_SOURCE_PAGES)
    result = extractor.extract(rendered.pages)
    text = "\n\n".join(page.text for page in result.pages).strip()
    if not text:
        raise KnowledgeError("source_text_empty", "파일에서 읽을 수 있는 글자를 찾지 못했습니다. 페이지와 이미지 상태를 확인해 주세요.")
    if len(text) > MAX_SOURCE_TEXT_CHARS:
        raise KnowledgeError("source_text_limit", "분석한 원문이 20,000자를 넘습니다. 파일을 나누어 읽어 주세요.")
    return {
        "filename": safe_name,
        "text": text,
        "page_count": rendered.page_count,
        "review_required": bool(
            rendered.warnings or result.warnings
            or any(not page.complete or page.uncertain or "[판독 불가]" in page.text for page in result.pages)
        ),
    }
