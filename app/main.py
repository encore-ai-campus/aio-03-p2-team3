from contextlib import asynccontextmanager
import logging
import secrets
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.clients.gmail import GoogleClient
from app.config import Settings, get_settings, validate_runtime
from app.db.engine import get_database
from app.graph.run import get_graph
from app.services.auth import GoogleAccess, make_cipher
from app.trade.common.models import DocumentError
from app.trade.common import api as trade_api
from app.trade.pi import router as pi_routes
from app.trade.po import router as po_routes
from app.trade.ci import router as ci_routes
from app.trade.pl import router as pl_routes
from app.trade.settings import router as trade_settings
from app.web import WEB, templates
from app.web.deps import LoginRequired
from app.web.routes import auth, candidates, gmail_push, inbox, pages, quotes, runs, settings as settings_routes

SESSION_MAX_AGE_SECONDS = 14 * 24 * 60 * 60


def create_app(settings: Settings | None = None, google=None) -> FastAPI:
    """google: Google 호출 객체. 비우면 실제 `GoogleClient`, 테스트는 가짜를 넣는다."""
    config = settings or get_settings()
    validate_runtime(config)
    same_site = config.session_same_site or "lax"
    if same_site not in {"lax", "strict", "none"}:
        raise ValueError("SESSION_SAME_SITE는 lax·strict·none 중 하나여야 합니다")
    if same_site == "none" and not config.app_base_url.startswith("https://"):
        raise ValueError("사이트가 다른 React와 세션을 공유하려면 HTTPS가 필요합니다")
    origins = [value.strip().rstrip("/") for value in config.frontend_origins.split(",") if value.strip()]
    for origin in origins:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("FRONTEND_ORIGINS에는 허용할 웹 출처만 입력하세요")

    @asynccontextmanager
    async def lifespan(app):
        database = get_database(config)
        app.state.settings = config
        app.state.database = database
        app.state.graph = get_graph()
        # 서버의 OPENAI_API_KEY는 사용하지 않는다. 사용자 키는 호출 시에만 읽는다.
        app.state.llm = None
        app.state.google = google or GoogleClient(config)
        app.state.google_access = GoogleAccess(
            database, app.state.google, make_cipher(config), config.gmail_pubsub_topic,
        )
        try:
            yield
        finally:
            database.close()

    app = FastAPI(title="Gmail 견적 도우미", lifespan=lifespan)
    if config.ai_runtime == "local":
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    if not config.session_secret:
        logging.getLogger(__name__).warning("SESSION_SECRET이 비어 임시 키를 씁니다(재시작하면 로그인이 풀림)")
    app.add_middleware(
        SessionMiddleware, secret_key=config.session_secret or secrets.token_urlsafe(32),
        session_cookie="gq_session", max_age=SESSION_MAX_AGE_SECONDS, same_site=same_site,
        https_only=config.app_base_url.startswith("https://"),
    )
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                           allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                           allow_headers=["Content-Type", "X-CSRF-Token"])
    app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")
    # 라우터 파일(app/web/routes/)은 request.app.state.templates(= app.web.templates)로 같은 템플릿을 쓴다.
    app.state.templates = templates
    app.include_router(auth.router)
    app.include_router(gmail_push.router)
    app.include_router(pages.router)
    app.include_router(quotes.router)
    app.include_router(settings_routes.router)
    app.include_router(trade_api.router)
    app.include_router(pi_routes.router)
    app.include_router(po_routes.router)
    app.include_router(ci_routes.router)
    app.include_router(pl_routes.router)
    app.include_router(trade_settings.router)

    @app.exception_handler(LoginRequired)
    def login_required(request: Request, _):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": {"code": "LOGIN_REQUIRED", "message": "로그인이 필요합니다"}}, status_code=401)
        return RedirectResponse("/login", status_code=303)

    @app.exception_handler(DocumentError)
    def document_error(request: Request, error: DocumentError):
        return JSONResponse({"error": {"code": error.code, "message": error.message}}, status_code=error.status_code)

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
