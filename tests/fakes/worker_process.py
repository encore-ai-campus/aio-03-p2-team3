"""별도 실제 프로세스 시험 전용. 운영 실행기의 목적지/인증 검증 옵션은 추가하지 않는다."""
import argparse
import json
import os
import sys

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
from langchain_openai import ChatOpenAI
import uvicorn


def serve():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["server", "openai", "pc"])
    parser.add_argument("--env")
    parser.add_argument("--port", type=int)
    parser.add_argument("--cert")
    parser.add_argument("--key")
    parser.add_argument("--mock-url")
    args, rest = parser.parse_known_args()
    if args.role == "pc":
        from app.worker import pc
        def backend(policy):
            return ChatOpenAI(model=policy.model, api_key=policy.key, base_url=args.mock_url,
                              use_responses_api=True, http_socket_options=(), max_retries=0, timeout=20,
                              max_tokens=policy.max_output_tokens)
        pc._backend = backend
        raise SystemExit(pc.main([*rest, "--env", args.env]))
    if args.role == "server":
        from app.config import Settings, get_settings
        from dotenv import load_dotenv
        for name in Settings.__dataclass_fields__:
            os.environ[name.upper()] = ""
        load_dotenv(args.env, override=True)
        settings = get_settings(args.env)
        from app.llm import client
        from app.main import create_app
        from tests.fakes.gmail import FakeGmailGoogle
        from tests.fakes.storage import FakeStorage
        def forbidden(*_):
            raise AssertionError("서버에서 OpenAI 키를 사용하면 안 됩니다")
        client._backend_for_settings = forbidden
        google = FakeGmailGoogle()
        from tests.fakes.gmail import message
        google.mailbox.raw_messages["fake-message"] = message(body="REFLECT 가상 문의입니다.")
        app = create_app(settings, google=google, storage=FakeStorage())
        @app.get("/test/state")
        def state():
            return {"sends": len(google.mailbox.called("send")), "watches": len(google.called("watch"))}
    else:
        app = FastAPI()
        calls = []
        @app.get("/test/state")
        def state():
            return calls
        @app.post("/v1/responses")
        async def responses(request: Request):
            body = await request.json()
            header = request.headers.get("authorization", "")
            tag = {"Bearer fake-pc-one": "one", "Bearer fake-pc-two": "two", "Bearer fake-pc-rotated": "rotated"}.get(header, "unexpected")
            name = body["tools"][0]["name"]
            source = str(body.get("input", ""))
            calls.append({"key_tag": tag, "schema": name, "tokens": body.get("max_output_tokens"), "model": body["model"],
                          "owner_marker": "one" if "OWNER1" in source else "two" if "OWNER2" in source else None})
            code = next((code for code in (401, 429, 503) if f"API{code}" in source), None)
            if code:
                return JSONResponse({"error": {"message": "fake-sensitive-sdk-error", "type": "fake_error"}}, status_code=code)
            values = {
                "EmailAnalysis": {"intent": "general", "reason": "가상 문의"},
                "DraftOutput": {"candidates": [{"label": "간단 안내", "body": "가상 답장입니다."},
                                               {"label": "상세 안내", "body": "가상 안내입니다."}]},
                "ExtractedDealTerms": {"customer_name": "가상상사", "items": [], "due_date": None},
                "ThreadSummary": {"deal_conditions": [], "confirmed_fields": [], "unanswered_questions": []},
                "ReflectAnalysis": {"cause": "가상 오류", "feedback": "금액을 제거하세요"},
            }.get(name, {})
            if name == "DraftOutput" and "REFLECT" in source and "금액을 제거하세요" not in source:
                values = {"candidates": [{"label": "오류 주입", "body": "금액은 100000원입니다."},
                                         {"label": "가상 안내", "body": "안내입니다."}]}
            return {"id": "resp_fake", "object": "response", "created_at": 1, "model": body["model"],
                    "status": "completed", "error": None, "incomplete_details": None,
                    "output": [{"type": "function_call", "id": "fc_fake", "call_id": "call_fake",
                                "name": name, "arguments": json.dumps(values)}],
                    "parallel_tool_calls": False, "tool_choice": body["tool_choice"], "tools": body["tools"],
                    "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10}}
    uvicorn.run(app, host="127.0.0.1", port=args.port, ssl_certfile=args.cert, ssl_keyfile=args.key,
                log_level="error", access_log=False)


if __name__ == "__main__":
    serve()
