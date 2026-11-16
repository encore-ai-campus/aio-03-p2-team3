"""지식 문서 입력의 형식·자원 검증. SDK/DB 없이 실행한다."""
from io import BytesIO
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

from app.knowledge.schemas import KnowledgeError, MAX_FILE_BYTES, MAX_UNPACKED_BYTES

MIME_TYPES = {
    ".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt": "text/plain; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
}


def validate_upload(filename: str, data: bytes) -> tuple[str, str]:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if not name.strip() or len(name) > 240 or any(ord(c) < 32 for c in name):
        raise KnowledgeError("invalid_filename", "파일 이름은 제어 문자 없이 240자 이내로 지정해 주세요.")
    if not data:
        raise KnowledgeError("empty_file", "빈 파일은 업로드할 수 없습니다.")
    if len(data) > MAX_FILE_BYTES:
        raise KnowledgeError("file_too_large", "파일은 20MiB 이하여야 합니다.", 413)
    extension = Path(name).suffix.lower()
    if extension not in MIME_TYPES:
        raise KnowledgeError("unsupported_format", "PDF·DOCX·XLSX·TXT·PNG·JPEG를 지원합니다. HWP는 PDF로 변환해 주세요.", 415)
    valid = False
    if extension == ".pdf":
        valid = b"%PDF-" in data[:1024]
    elif extension == ".png":
        valid = data.startswith(b"\x89PNG\r\n\x1a\n")
    elif extension in {".jpg", ".jpeg"}:
        valid = data.startswith(b"\xff\xd8\xff")
    elif extension == ".txt":
        try:
            data.decode("utf-8")
            valid = b"\x00" not in data and b"%PDF-" not in data[:1024] and not data.startswith(b"PK")
        except UnicodeDecodeError:
            pass
    else:
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                entries = archive.infolist()
                if (len(entries) > 2000 or sum(e.file_size for e in entries) > MAX_UNPACKED_BYTES
                        or any(e.flag_bits & 1 or ".." in Path(e.filename).parts for e in entries)):
                    raise KnowledgeError("archive_limit", "암호화되었거나 압축 해제 한도를 넘는 문서입니다.")
                names = set(archive.namelist())
                if any(name.lower().endswith("vbaproject.bin") for name in names):
                    raise KnowledgeError("unsafe_office_content", "매크로가 있는 문서는 PDF로 변환해 업로드해 주세요.")
                for relation in (name for name in names if name.endswith(".rels")):
                    for node in ET.fromstring(archive.read(relation)).iter():
                        if (node.get("TargetMode") == "External"
                                and not node.get("Type", "").endswith("/hyperlink")):
                            raise KnowledgeError("unsafe_office_content", "외부 파일을 읽는 연결이 있습니다. 연결을 제거하거나 PDF로 변환해 주세요.")
                part = "word/document.xml" if extension == ".docx" else "xl/workbook.xml"
                valid = "[Content_Types].xml" in names and part in names
        except (zipfile.BadZipFile, ValueError, ET.ParseError):
            pass
    if not valid:
        raise KnowledgeError("signature_mismatch", "파일 내용과 확장자가 일치하지 않거나 파일이 손상되었습니다.", 415)
    return name, MIME_TYPES[extension]
