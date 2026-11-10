"""기본 화면과 정적 자산. 화면 경로들은 여기의 `templates` 하나를 함께 쓴다."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

WEB = Path(__file__).parent
templates = Jinja2Templates(directory=WEB / "templates")
