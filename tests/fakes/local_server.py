"""실제 app.local 소켓/수명 검증 전용 서버. 외부 Google·OpenAI 대신 대역을 주입한다."""
import argparse
import os
import socket
import sys

from fastapi import Request
import pytest
from sqlalchemy import func, select

from app.config import Settings, get_settings, local_listener
from app.db.models import ReplyCandidate
from app.services.local_gmail import LocalGmailCollector
from tests.fakes.gmail import FakeGmailGoogle


def serve():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--port", required=True)
    args = parser.parse_args()
    from dotenv import load_dotenv
    for name in Settings.__dataclass_fields__:
        os.environ[name.upper()] = ""
    load_dotenv(args.env, override=True)
    get_settings.cache_clear()
    get_settings(args.env)
    from app import local
    # main의 모듈 앱 생성도 실제 루프백 수신 소켓 범위에서만 허용한다.
    with socket.socket() as bootstrap:
        bootstrap.bind(("127.0.0.1", 0))
        with local_listener(bootstrap):
            from app import main
    from tests.test_openai_keys import sdk
    google = FakeGmailGoogle()
    original = main.create_app
    with pytest.MonkeyPatch.context() as patch:
        mock_sdk = sdk.__wrapped__(patch)
        calls = next(mock_sdk)

        def create_app(settings):
            app = original(settings, google=google)

            @app.get("/test/state")
            def state(request: Request):
                with request.app.state.database.session() as session:
                    candidates = session.scalar(select(func.count()).select_from(ReplyCandidate))
                return {"ai_calls": len(calls),
                        "candidates": candidates,
                        "local_key_only": all(auth == "Bearer fake-local-private-key" for auth, _ in calls),
                        "sends": len(google.mailbox.called("send")),
                        "watches": len(google.called("watch")), "stops": len(google.called("stop")),
                        "reads": len(google.mailbox.called("history"))}

            return app

        patch.setattr(main, "create_app", create_app)
        # 템플릿의 30초 안내와 운영 주기는 그대로 두고 실행 시험만 빨리 돌린다.
        patch.setattr(main, "LocalGmailCollector", lambda access: LocalGmailCollector(access, interval=0.05))
        sys.argv = ["app.local", "--port", args.port]
        try:
            local.main()
        finally:
            mock_sdk.close()


if __name__ == "__main__":
    serve()
