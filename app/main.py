from contextlib import asynccontextmanager
import logging
import secrets

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.clients.gmail import GoogleClient
from app.config import Settings, get_settings
from app.db.engine import get_database
from app.db.models import User
from app.graph.run import get_graph
from app.llm.client import get_backend
from app.services.auth import GoogleAccess, make_cipher
from app.web import WEB, templates
from app.web.routes import auth

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
    app.include_router(auth.router)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/inbox", status_code=303)

    @app.get("/inbox", include_in_schema=False)
    def inbox(request: Request, user: User | None = Depends(auth.current_user)):
        status = auth.connection_status(request, user) if user else None
        return templates.TemplateResponse(
            request=request, name="pages/inbox.html", context={"user": user, "status": status},
        )

    return app


app = create_app()
