"""파일을 제한된 자식 프로세스에서 페이지 PNG로 변환한다. 텍스트 추출은 하지 않는다."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
import warnings
import zipfile

from app.knowledge.schemas import (
    KnowledgeError, MAX_PAGES, MAX_PIXELS, MAX_UNPACKED_BYTES, PageImage, RenderedDocument,
)
from app.knowledge.validation import validate_upload

RENDER_VERSION = "pdfium-pages-v1"



class PageRenderer:
    def __init__(self, office_command: str = "", timeout: int = 120):
        self.office_command, self.timeout = office_command, timeout

    def render(self, data: bytes, filename: str, page_number: int | None = None) -> RenderedDocument:
        name, _ = validate_upload(filename, data)
        with TemporaryDirectory(prefix="knowledge-") as temporary:
            directory = Path(temporary)
            source = directory / ("input" + Path(name).suffix.lower())
            source.write_bytes(data)
            # 변환기에 DB·AI 키를 넘기지 않는다. 명령/경로는 서버 설정과 임시 경로뿐이다.
            environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "LANG") if key in os.environ}
            environment.update(HOME=temporary, TMPDIR=temporary, TEMP=temporary, TMP=temporary,
                               PYTHONPATH=str(Path(__file__).resolve().parents[2]))
            command = [sys.executable, "-m", "app.knowledge.render", str(source), str(directory),
                       self.office_command, str(page_number or 0)]
            try:
                with subprocess.Popen(command, cwd=temporary, env=environment,
                                      start_new_session=os.name == "posix",
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as process:
                    try:
                        returncode = process.wait(timeout=self.timeout)
                    except subprocess.TimeoutExpired:
                        if os.name == "posix":
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                        process.kill()
                        process.wait()
                        raise
            except subprocess.TimeoutExpired:
                raise KnowledgeError("render_timeout", "페이지 변환 시간이 초과되었습니다. 문서를 나누어 업로드해 주세요.") from None
            manifest_path = directory / "manifest.json"
            if not manifest_path.exists():
                raise KnowledgeError("render_failed", "문서를 변환하지 못했습니다. 손상·암호화 여부를 확인해 주세요.")
            manifest = json.loads(manifest_path.read_text())
            if returncode or "error" in manifest:
                raise KnowledgeError(manifest.get("error", "render_failed"), manifest.get("message", "문서 변환에 실패했습니다."),
                                     manifest.get("status", 422))
            pages = [PageImage(p["number"], p["source"], (directory / p["file"]).read_bytes())
                     for p in manifest["pages"]]
            return RenderedDocument(pages, manifest["warnings"], manifest["page_count"])


def _office_pdf(source: Path, directory: Path, office_command: str):
    command = office_command or shutil.which("soffice") or shutil.which("libreoffice")
    if not command:
        raise KnowledgeError("office_not_installed", "DOCX·XLSX·TXT 변환에는 서버에 LibreOffice가 필요합니다. PDF로 변환해 업로드할 수도 있습니다.")
    if source.suffix == ".xlsx":
        from xml.etree import ElementTree as ET
        with zipfile.ZipFile(source) as archive:
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            if any(node.get("state", "visible") != "visible" for node in workbook.iter() if node.tag.endswith("}sheet")):
                raise KnowledgeError("hidden_sheet", "숨김 시트를 표시하거나 필요한 내용을 PDF로 내보낸 뒤 업로드해 주세요.")
            for name in archive.namelist():
                if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                    sheet = ET.fromstring(archive.read(name))
                    namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                    for cell in sheet.findall(".//s:c", namespace):
                        value = cell.find("s:v", namespace)
                        if cell.find("s:f", namespace) is not None and (value is None or value.text is None):
                            raise KnowledgeError("formula_cache_missing", "수식 결과가 없는 셀이 있습니다. Excel에서 재계산·저장하거나 PDF로 내보내 주세요.")
    profile = (directory / "office-profile").as_uri()
    result = subprocess.run([command, "-env:UserInstallation=" + profile, "--headless", "--nologo",
                             "--nodefault", "--norestore", "--convert-to", "pdf", "--outdir", str(directory),
                             str(source)], timeout=75, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    output = source.with_suffix(".pdf")
    if result.returncode or not output.exists() or output.stat().st_size > MAX_UNPACKED_BYTES:
        raise KnowledgeError("office_conversion_failed", "Office 문서를 PDF로 변환하지 못했습니다. PDF로 내보내 업로드해 주세요.")
    return output


def _render_child(source: Path, directory: Path, office_command: str, page_number: int):
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    notices, pages = [], []
    page_count = 1
    converted = source.suffix not in {".pdf", ".png", ".jpg", ".jpeg"}
    if converted:
        source = _office_pdf(source, directory, office_command)
        notices.append("converted_layout_requires_review")

    def save(image, number, label):
        if image.width * image.height > MAX_PIXELS:
            raise KnowledgeError("image_limit", "이미지는 2천만 픽셀 이하여야 합니다.")
        image.thumbnail((3000, 3000))
        target = directory / f"page-{number}.png"
        image.convert("RGB").save(target)
        if sum(p.stat().st_size for p in directory.glob("page-*.png")) > MAX_UNPACKED_BYTES:
            raise KnowledgeError("render_size_limit", "페이지 이미지 합계가 100MiB를 넘습니다. 문서를 나누어 주세요.")
        pages.append({"number": number, "source": label, "file": target.name})

    if source.suffix == ".pdf":
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(source) as pdf:
            page_count = len(pdf)
            if len(pdf) < 1 or len(pdf) > MAX_PAGES:
                raise KnowledgeError("page_limit", "변환 후 총 1~50페이지 문서만 지원합니다.")
            if page_number > len(pdf):
                raise KnowledgeError("page_not_found", "해당 페이지가 없습니다.", 404)
            indices = [page_number - 1] if page_number else range(len(pdf))
            for index in indices:
                page = pdf[index]
                try:
                    width, height = page.get_size()
                    if width <= 0 or height <= 0:
                        raise KnowledgeError("invalid_page", "페이지 크기를 읽을 수 없습니다.")
                    if max(width, height) > 1500:
                        notices.append("large_page_requires_review")
                    bitmap = page.render(scale=min(2, 3000 / max(width, height)))
                    try:
                        save(bitmap.to_pil(), index + 1,
                             f"{'변환' if converted else '원본'} 페이지 {index + 1}")
                    finally:
                        bitmap.close()
                finally:
                    page.close()
    else:
        if page_number > 1:
            raise KnowledgeError("page_not_found", "해당 페이지가 없습니다.", 404)
        with Image.open(source) as image:
            if image.width * image.height > MAX_PIXELS:
                raise KnowledgeError("image_limit", "이미지는 2천만 픽셀 이하여야 합니다.")
            save(ImageOps.exif_transpose(image), 1, "원본 이미지 1")
    return {"pages": pages, "warnings": list(dict.fromkeys(notices)), "page_count": page_count}


def main():
    source, directory = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        if sys.platform.startswith("linux"):
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 * 1024,) * 2)
            resource.setrlimit(resource.RLIMIT_CPU, (100, 100))
            resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_UNPACKED_BYTES,) * 2)
        manifest = _render_child(source, directory, sys.argv[3], int(sys.argv[4]))
        status = 0
    except KnowledgeError as error:
        manifest, status = {"error": error.code, "message": error.message, "status": error.status}, 1
    except Exception:
        manifest, status = {"error": "render_failed", "message": "페이지 변환에 실패했습니다. 파일의 손상·암호화 여부를 확인해 주세요."}, 1
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
