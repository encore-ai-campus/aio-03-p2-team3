from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.db.engine import get_database
from app.graph.run import get_graph
from app.llm.client import get_backend

WEB = Path(__file__).parent / "web"


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        config = settings or get_settings()
        database = get_database(config)
        app.state.settings = config
        app.state.database = database
        app.state.graph = get_graph()
        # API 키가 없어도 기본 화면과 healthz는 사용할 수 있다.
        app.state.llm = get_backend(config) if config.gemini_api_key else None
        try:
            yield
        finally:
            database.close()

    app = FastAPI(title="Gmail 견적 도우미", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")
    templates = Jinja2Templates(directory=WEB / "templates")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/inbox", status_code=303)

    @app.get("/inbox", include_in_schema=False)
    def inbox(request: Request):
        return templates.TemplateResponse(request=request, name="pages/inbox.html")

    return app


app = create_app()
