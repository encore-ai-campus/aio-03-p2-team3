from contextlib import asynccontextmanager
import logging
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.clients.gmail import GoogleClient
from app.config import Settings, get_settings
from app.db.engine import get_database
from app.graph.run import get_graph
from app.llm.client import get_backend
from app.services.auth import GoogleAccess, make_cipher
from app.web import WEB, templates
from app.web.deps import LoginRequired
from app.web.routes import auth, candidates, gmail_push, inbox, pages, runs

SESSION_MAX_AGE_SECONDS = 14 * 24 * 60 * 60


def create_app(settings: Settings | None = None, google=None) -> FastAPI:
    """google: Google 호출 객체. 비우면 실제 `GoogleClient`, 테스트는 가짜를 넣는다."""
    config = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app):
        database = get_database(config)
        app.state.settings = config
        app.state.database = database
        app.state.graph = get_graph()
        # API 키가 없어도 기본 화면과 healthz는 사용할 수 있다.
        app.state.llm = get_backend(config) if config.gemini_api_key else None
        app.state.google = google or GoogleClient(config)
        app.state.google_access = GoogleAccess(
            database, app.state.google, make_cipher(config), config.gmail_pubsub_topic,
        )
        try:
            yield
        finally:
            database.close()

    app = FastAPI(title="Gmail 견적 도우미", lifespan=lifespan)
    if not config.session_secret:
        logging.getLogger(__name__).warning("SESSION_SECRET이 비어 임시 키를 씁니다(재시작하면 로그인이 풀림)")
    app.add_middleware(
        SessionMiddleware, secret_key=config.session_secret or secrets.token_urlsafe(32),
        session_cookie="gq_session", max_age=SESSION_MAX_AGE_SECONDS, same_site="lax",
        https_only=config.app_base_url.startswith("https://"),
    )
    app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")
    # 라우터 파일(app/web/routes/)은 request.app.state.templates(= app.web.templates)로 같은 템플릿을 쓴다.
    app.state.templates = templates
    app.include_router(auth.router)
    app.include_router(gmail_push.router)
    app.include_router(pages.router)

    @app.exception_handler(LoginRequired)
    def login_required(request: Request, _):
        return RedirectResponse("/login", status_code=303)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/inbox", status_code=303)

    app.include_router(inbox.router)
    app.include_router(candidates.router)
    app.include_router(runs.router)
    return app


app = create_app()
