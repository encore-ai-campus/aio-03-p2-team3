"""개인 PC 전용 실행: uv run python -m app.local [--port 8000]."""
import argparse
import socket

import uvicorn

from app.config import get_settings, local_listener, validate_runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    settings = get_settings()
    if settings.ai_runtime != "local":
        parser.error("로컬 .env에 AI_RUNTIME=local을 지정하세요")
    # 호스트·리로드·워커 옵션을 받지 않고 검증한 소켓 자체를 uvicorn에 넘긴다.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", args.port))
        with local_listener(listener):
            validate_runtime(settings)
            from app.main import create_app

            server = uvicorn.Server(uvicorn.Config(
                create_app(settings), host="127.0.0.1", port=args.port, proxy_headers=False,
            ))
            server.run(sockets=[listener])


if __name__ == "__main__":
    main()
