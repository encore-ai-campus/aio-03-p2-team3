"""HTTPS outbound용 장치 API와 로그인/CSRF로 보호하는 사용자 설정 API."""
import asyncio
import json
import secrets
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import ValidationError

from app.llm.client import model_name
from app.web.deps import current_user_id
from app.web.routes.settings import check_key_csrf
from app.worker import service
from app.worker.protocol import (
    ApprovePair, ExecutionMode, MAX_JSON_BYTES, PairPoll, PairRequest, StrictModel,
    WorkerError, manifest,
)


def transport(request: Request):
    if request.app.state.settings.ai_runtime != "server":
        raise WorkerError("worker_server_only", 409)
    if request.url.scheme != "https" or not request.app.state.settings.app_base_url.startswith("https://"):
        raise WorkerError("https_required", 400)


router = APIRouter(dependencies=[Depends(transport)])


def limited(request, action, limit=120, seconds=60, user_id=None):
    identity = f"user:{user_id}" if user_id is not None else f"ip:{request.client.host if request.client else 'unknown'}"
    service.rate_limit(request.app.state.database, identity, action, limit, seconds)


async def body(request, schema=None, *, csrf=False):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_JSON_BYTES:
            raise WorkerError("payload_too_large", 413)
    try:
        if request.headers.get("content-type", "").split(";")[0] == "application/x-www-form-urlencoded":
            values = parse_qs(raw.decode(), keep_blank_values=True, max_num_fields=20)
            if any(len(v) != 1 for v in values.values()):
                raise WorkerError()
            value = {k: v[0] for k, v in values.items()}
        else:
            def unique(pairs):
                result = {}
                for k, v in pairs:
                    if k in result:
                        raise WorkerError()
                    result[k] = v
                return result
            value = json.loads(raw, object_pairs_hook=unique,
                               parse_constant=lambda _: (_ for _ in ()).throw(WorkerError()))
        if not isinstance(value, dict):
            raise WorkerError()
        if csrf:
            token = value.pop("csrf_token", "") or request.headers.get("x-csrf-token", "")
            if not isinstance(token, str) or len(token) > 256:
                raise WorkerError("csrf_required", 403)
            check_key_csrf(request, token)
        return schema.model_validate(value) if schema else value
    except (ValidationError, ValueError, TypeError, UnicodeError, RecursionError):
        raise WorkerError() from None


def response(value):
    return JSONResponse(value, headers={"Cache-Control": "private, no-store", "Pragma": "no-cache"})


def setting_response(request, value):
    if request.url.path.startswith("/settings/"):
        return RedirectResponse("/settings#local-worker", status_code=303,
                                headers={"Cache-Control": "private, no-store"})
    return response(value)


def bearer(request):
    value = request.headers.get("authorization", "")
    if not value.startswith("Bearer ") or not 40 <= len(value[7:]) <= 100:
        raise WorkerError("unauthorized", 401)
    return value[7:]


@router.get("/api/worker/protocol")
def protocol(request: Request):
    limited(request, "protocol", 60)
    return response(manifest(model_name(request.app.state.settings)))


@router.post("/api/worker/pairings")
async def pair(request: Request):
    limited(request, "pair", 6, 600)
    parsed = await body(request, PairRequest)
    return response(service.start_pairing(request.app.state.database, parsed, model_name(request.app.state.settings)))


@router.post("/api/worker/pairings/{pairing_id}/poll")
async def poll(request: Request, pairing_id: str):
    limited(request, "pair-poll", 120)
    parsed = await body(request, PairPoll)
    return response(service.poll_pairing(request.app.state.database, pairing_id, parsed.device_secret))


@router.get("/api/ai-execution")
def execution_status(request: Request, user_id: int = Depends(current_user_id)):
    limited(request, "status", 60, user_id=user_id)
    request.session.setdefault("trade_csrf", secrets.token_urlsafe(32))
    return response({**service.status(request.app.state.database, user_id), "csrf_token": request.session["trade_csrf"]})


@router.post("/api/ai-execution/mode")
@router.post("/settings/worker/mode", include_in_schema=False)
async def mode(request: Request, user_id: int = Depends(current_user_id)):
    limited(request, "mode", 20, user_id=user_id)
    parsed = await body(request, ExecutionMode, csrf=True)
    return setting_response(request, service.set_mode(request.app.state.database, user_id, parsed.ai_execution_mode))


@router.post("/api/ai-execution/pairings/approve")
@router.post("/settings/worker/approve", include_in_schema=False)
async def approve(request: Request, user_id: int = Depends(current_user_id)):
    limited(request, "approve", 10, 600, user_id=user_id)
    parsed = await body(request, ApprovePair, csrf=True)
    return setting_response(request, service.approve_pairing(request.app.state.database, user_id, parsed.pairing_code, parsed.device_name))


@router.post("/api/ai-execution/devices/{device_id}/disconnect")
@router.post("/settings/worker/devices/{device_id}/disconnect", include_in_schema=False)
async def disconnect(request: Request, device_id: str, user_id: int = Depends(current_user_id)):
    limited(request, "disconnect", 20, user_id=user_id)
    await body(request, StrictModel, csrf=True)
    return setting_response(request, service.disconnect(request.app.state.database, user_id, device_id))


@router.post("/api/ai-execution/jobs/{job_id}/cancel")
async def cancel(request: Request, job_id: str, user_id: int = Depends(current_user_id)):
    limited(request, "cancel", 30, user_id=user_id)
    await body(request, StrictModel, csrf=True)
    return response(service.cancel(request.app.state.database, user_id, job_id))


@router.post("/api/worker/devices/{device_id}/claim")
async def claim(request: Request, device_id: str):
    limited(request, "claim")
    class Claim(StrictModel):
        wait_seconds: int = 0
    parsed = await body(request, Claim)
    if not 0 <= parsed.wait_seconds <= 25:
        raise WorkerError()
    token = bearer(request)
    deadline = asyncio.get_running_loop().time() + parsed.wait_seconds
    while True:
        # Windows 강제 종료/연결 끊김 뒤 남은 long poll이 새 작업을 임대하지 않게 한다.
        if await request.is_disconnected():
            return response({"job": None})
        result = await asyncio.to_thread(service.claim, request.app.state.database, device_id, token,
                                         model_name(request.app.state.settings))
        if result["job"] is not None or asyncio.get_running_loop().time() >= deadline:
            return response(result)
        if await request.is_disconnected():
            return response({"job": None})
        await asyncio.sleep(min(1, max(0, deadline - asyncio.get_running_loop().time())))


@router.post("/api/worker/devices/{device_id}/jobs/{job_id}/heartbeat")
async def heartbeat(request: Request, device_id: str, job_id: str):
    limited(request, "heartbeat")
    class Heartbeat(StrictModel):
        attempt_id: str
    parsed = await body(request, Heartbeat)
    return response(service.heartbeat(request.app.state.database, device_id, bearer(request), job_id, parsed.attempt_id))


@router.post("/api/worker/devices/{device_id}/jobs/{job_id}/complete")
async def complete(request: Request, device_id: str, job_id: str):
    limited(request, "complete")
    parsed = await body(request)
    return response(service.complete(request.app.state.database, device_id, bearer(request), job_id, parsed,
                                     cipher=request.app.state.google_access.cipher))
