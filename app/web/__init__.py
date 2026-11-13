"""공유 HTML 템플릿·정적 자산. 업무 경로와 인증은 각 도메인이 담당한다."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

WEB = Path(__file__).parent
templates = Jinja2Templates(directory=WEB / "templates")
