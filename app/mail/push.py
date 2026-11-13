"""인증된 Pub/Sub 알림에 204를 보내고 응답 뒤 같은 프로세스에서 처리한다."""

from base64 import b64decode
import binascii
import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response

from app.services.gmail_push import process_notification

router = APIRouter()
log = logging.getLogger(__name__)


def _verify_push(request: Request):
    settings = request.app.state.settings
    try:
        if settings.pubsub_push_audience or settings.pubsub_push_service_account:
            if not settings.pubsub_push_audience or not settings.pubsub_push_service_account:
                raise ValueError("OIDC 설정 누락")
            scheme, _, token = request.headers.get("authorization", "").partition(" ")
            if scheme.lower() != "bearer" or not token:
                raise ValueError("Bearer 토큰 누락")
            request.app.state.google.verify_push_token(
                token, settings.pubsub_push_audience, settings.pubsub_push_service_account,
            )
        elif not settings.pubsub_push_token or not hmac.compare_digest(
            request.query_params.get("token", "").encode(), settings.pubsub_push_token.encode(),
        ):
            raise ValueError("푸시 토큰 불일치")
    except Exception:
        log.warning("Gmail 푸시 요청 인증 실패")
        raise HTTPException(status_code=403, detail="푸시 요청 인증 실패") from None


@router.post("/gmail/push", status_code=204, dependencies=[Depends(_verify_push)])
async def gmail_push(request: Request, background_tasks: BackgroundTasks):
    try:
        envelope = await request.json()
        encoded = envelope["message"]["data"]
        data = json.loads(b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True))
        address, history_id = data["emailAddress"], data["historyId"]
        if not isinstance(address, str) or "@" not in address:
            raise ValueError("emailAddress 오류")
        if not isinstance(history_id, (str, int)) or isinstance(history_id, bool):
            raise ValueError("historyId 오류")
        history_id = str(history_id)
        if not history_id.isascii() or not history_id.isdecimal() or int(history_id) <= 0:
            raise ValueError("historyId 오류")
    except (KeyError, TypeError, ValueError, binascii.Error):
        raise HTTPException(status_code=400, detail="Gmail 알림 형식 오류") from None
    background_tasks.add_task(
        process_notification, request.app.state.google_access, address, history_id,
        graph=request.app.state.graph,
    )
    return Response(status_code=204)
