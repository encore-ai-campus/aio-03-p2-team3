"""React 빌드만 /app 아래 제공한다. API·OAuth·Pub/Sub에는 fallback을 적용하지 않는다."""

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class FrontendFiles(StaticFiles):
    async def check_config(self) -> None:
        # 프론트를 빌드하지 않은 개발 환경에서도 기존 서버 경로는 사용할 수 있다.
        # StaticFiles.lookup_path가 없는 디렉터리·경로 이탈·외부 symlink를 거부한다.
        pass

    async def get_response(self, path, scope):
        if scope["method"] not in {"GET", "HEAD"}:
            return await super().get_response(path, scope)
        page = Path(path)
        if any(part.startswith(".") for part in page.parts):
            raise HTTPException(status_code=404)
        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            # 누락된 JS/CSS/이미지와 assets 안의 요청에는 HTML을 반환하지 않는다.
            if error.status_code != 404 or page.suffix or (page.parts and page.parts[0] == "assets"):
                raise
            try:
                response = await super().get_response("index.html", scope)
            except HTTPException as missing:
                if missing.status_code != 404:
                    raise
                raise HTTPException(status_code=503, detail="UI 빌드가 없습니다. frontend 빌드를 실행하세요.") from None
        # index와 상세 주소는 매번 재검증한다. 정적 파일은 ETag/Last-Modified로 재사용한다.
        response.headers["Cache-Control"] = "no-cache"
        return response
