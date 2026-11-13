from contextlib import asynccontextmanager
import asyncio
import logging
import secrets
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.auth import gmail as gmail_connection
from app.auth import router as supabase_me
from app.auth import session as session_routes
from app.auth.deps import LoginRequired
from app.auth.gmail import GmailConnectionError
from app.auth.supabase import BearerAuthError, TokenVerifier
from app.clients.gmail import GoogleClient
from app.config import Settings, get_settings, validate_runtime
from app.db.engine import get_database
from app.files import router as files_routes
from app.files.service import FileError
from app.files.storage import StorageClient
from app.graph.run import get_graph
from app.mail import candidates, inbox, push as gmail_push
from app.quote import router as quotes
from app.runlog import router as runs
from app.services.auth import GoogleAccess, make_cipher
from app.services.local_gmail import LocalGmailCollector
from app.settings import router as settings_routes
from app.trade.common.models import DocumentError
from app.trade.common import api as trade_api
from app.trade.pi import router as pi_routes
from app.trade.po import router as po_routes
from app.trade.ci import router as ci_routes
from app.trade.pl import router as pl_routes
from app.trade.settings import router as trade_settings
from app.web import WEB, frontend, pages, templates
from app.worker import router as worker_routes, service as worker_service
from app.worker.protocol import WorkerError

SESSION_MAX_AGE_SECONDS = 14 * 24 * 60 * 60


def create_app(settings: Settings | None = None, google=None,
               supabase_auth: TokenVerifier | None = None, storage=None) -> FastAPI:
    """google: Google 호출 객체. 비우면 실제 `GoogleClient`, 테스트는 가짜를 넣는다.
    supabase_auth: Supabase 토큰 검증기. 비우면 SUPABASE_URL로 만들고, 그것도 없으면 Bearer 인증 불가(503).
    storage: Storage 호출 객체. 비우면 SUPABASE_URL·SUPABASE_SECRET_KEY로 만들고, 없으면 파일 API 503."""
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
        app.state.supabase_auth = supabase_auth or (
            TokenVerifier(config.supabase_url, secret_key=config.supabase_secret_key)
            if config.supabase_url.strip() else None
        )
        # 비공개 Storage 버킷 호출기(계획 8절). 서버 키가 없으면 파일 API를 503으로 막는다.
        app.state.storage = storage or (
            StorageClient(config.supabase_url, config.supabase_secret_key,
                          config.supabase_storage_bucket.strip() or "trade-files")
            if config.supabase_url.strip() and config.supabase_secret_key.strip() else None
        )
        # 서버의 OPENAI_API_KEY는 사용하지 않는다. 사용자 키는 호출 시에만 읽는다.
        app.state.llm = None
        app.state.google = google or GoogleClient(config)
        app.state.google_access = GoogleAccess(
            database, app.state.google, make_cipher(config), config.gmail_pubsub_topic,
            settings=config,
        )
        collector = LocalGmailCollector(app.state.google_access) if config.ai_runtime == "local" else None
        app.state.local_gmail = collector
        task = asyncio.create_task(collector.run()) if collector else None
        worker_stop = asyncio.Event()
        async def clean_worker_queue():
            while not worker_stop.is_set():
                try:
                    await asyncio.wait_for(worker_stop.wait(), timeout=5)
                except TimeoutError:
                    try:
                        await asyncio.to_thread(worker_service.cleanup, database)
                    except Exception as error:
                        logging.getLogger(__name__).error("장치 큐 정리 실패 (%s)", type(error).__name__)

        if config.ai_runtime == "server":
            worker_service.cleanup(database)
        worker_task = asyncio.create_task(clean_worker_queue()) if config.ai_runtime == "server" else None
        try:
            yield
        finally:
            if worker_task:
                worker_stop.set()
                await worker_task  # 정리 스레드가 끝난 다음 DB를 닫는다.
            if collector:
                collector.stop()
                await task  # 작업 스레드가 멈춘 다음 DB를 닫는다.
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
                           allow_headers=["Content-Type", "X-CSRF-Token", "Authorization"])
    app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")
    # 도메인 라우터는 request.app.state.templates(= app.web.templates)로 화면 자산을 공유한다.
    app.state.templates = templates
    app.include_router(session_routes.router)
    app.include_router(gmail_push.router)
    app.include_router(pages.router)
    app.include_router(quotes.router)
    app.include_router(settings_routes.router)
    app.include_router(supabase_me.router)
    app.include_router(gmail_connection.router)
    app.include_router(files_routes.router)
    app.include_router(worker_routes.router)
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

    @app.exception_handler(BearerAuthError)
    def bearer_auth_error(request: Request, error: BearerAuthError):
        return JSONResponse({"error": {"code": error.code, "message": error.message}}, status_code=error.status_code)

    @app.exception_handler(GmailConnectionError)
    def gmail_connection_error(request: Request, error: GmailConnectionError):
        return JSONResponse({"error": {"code": error.code, "message": error.message}}, status_code=error.status_code)

    @app.exception_handler(FileError)
    def file_error(request: Request, error: FileError):
        return JSONResponse({"error": {"code": error.code, "message": error.message}}, status_code=error.status_code)
    @app.exception_handler(WorkerError)
    def worker_error(request: Request, error: WorkerError):
        return JSONResponse({"error": {"code": error.code}}, status_code=error.status,
                            headers={"Cache-Control": "private, no-store", "Retry-After": "5"} if error.status == 429
                            else {"Cache-Control": "private, no-store"})

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/inbox", status_code=303)

    app.include_router(inbox.router)
    app.include_router(candidates.router)
    app.include_router(runs.router)
    app.mount("/app", frontend.FrontendFiles(directory=frontend.DIST, check_dir=False), name="frontend")
    return app


app = create_app()
