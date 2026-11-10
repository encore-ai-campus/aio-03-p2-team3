"""실행 기록 화면·내보내기 — `docs/CONTRACT.md` 8절·9절, 계획 14절(R-12).

본인 실행만 보이고(`current_user_id`), 화면도 내보내기 파일과 같은 규칙으로 개인정보를 가린다.
"""
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.runlog.export import export_jsonl, list_runs, load_run, run_records
from app.web.deps import current_user_id

router = APIRouter()
KST = timezone(timedelta(hours=9), "KST")

EVENT_LABELS = {
    "run_start": "실행 시작", "node_start": "노드 시작", "node_end": "노드 끝", "route": "다음 노드",
    "tool_select": "도구 선택", "tool_call": "도구 호출", "tool_result": "도구 결과",
    "llm_call": "LLM 호출", "retry": "재시도", "reflection": "성찰", "required_source": "필수 항목 출처",
    "error": "오류", "approval": "승인", "send": "발송", "run_end": "실행 끝",
}
END_LABELS = {
    "awaiting_approval": "승인 대기", "followup_question": "추가 질문", "ignored": "처리 안 함",
    "failed": "실패", None: "진행 중",
}
# 화면에서 눈에 띄게 할 줄(오류·재시도·실패한 도구·LLM 결과)
WARN_EVENTS = {"error", "retry"}


def _kst(value: str | None) -> str:
    if not value:
        return "—"
    return datetime.fromisoformat(value).astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def _short(value) -> str:
    if isinstance(value, list):
        return ", ".join(_short(v) for v in value) or "없음"
    if isinstance(value, dict):
        return ", ".join(f"{k}={_short(v)}" for k, v in value.items() if v not in (None, [], {}))
    return "—" if value is None else str(value)


def describe(event: str, detail: dict) -> str:
    """한 줄 요약. 다 담지 못한 값은 화면의 '전체 값'에서 본다."""
    if event == "route":
        reason = detail.get("reason")
        return f"→ {detail.get('to')}" + (f" (근거: {_short(reason)})" if reason else "")
    if event == "node_end":
        return f"상태 {detail.get('step_status')} · 바뀐 필드: {_short(detail.get('changed_fields', []))}"
    if event == "tool_select":
        return f"이유: {_short(detail.get('reason'))}"
    if event in {"tool_result", "llm_call", "approval", "send"}:
        ok = "성공" if detail.get("ok") else "실패"
        rest = {k: v for k, v in detail.items() if k != "ok"}
        return f"{ok}" + (f" · {_short(rest)}" if _short(rest) else "")
    if event == "error":
        return f"{detail.get('kind')}: {detail.get('message')}"
    if event == "run_end":
        return (f"{END_LABELS.get(detail.get('end_reason'), detail.get('end_reason'))} · "
                f"통신 재시도 {detail.get('call_retries', 0)}회 · 성찰 재실행 {detail.get('reflection_retries', 0)}회")
    return _short(detail)


def _event_rows(run: dict, events: list[dict]) -> list[dict]:
    started = datetime.fromisoformat(run["started_at"])
    rows = []
    for e in events:
        detail = e["detail"] or {}
        failed = e["event"] in {"tool_result", "llm_call", "send"} and detail.get("ok") is False
        rows.append({
            **e,
            "label": EVENT_LABELS.get(e["event"], e["event"]),
            "elapsed_ms": max(0, int((datetime.fromisoformat(e["at"]) - started).total_seconds() * 1000)),
            "summary": describe(e["event"], detail),
            "raw": json.dumps(detail, ensure_ascii=False, indent=1),
            "warn": e["event"] in WARN_EVENTS or failed,
        })
    return rows


def _counts(events: list[dict]) -> dict:
    def count(*names):
        return sum(1 for e in events if e["event"] in names)
    return {
        "nodes": count("node_end"), "tools": count("tool_call"), "llm": count("llm_call"),
        "retries": count("retry"), "errors": count("error"), "reflections": count("reflection"),
    }


@router.get("/runs", include_in_schema=False)
def runs_page(request: Request, user_id: int = Depends(current_user_id)):
    runs = [{
        "run_id": r.run_id, "mode": r.mode, "scenario": r.scenario,
        "reflection_enabled": r.reflection_enabled, "started": _kst(r.started_at.isoformat()),
        "end_label": END_LABELS.get(r.end_reason, r.end_reason), "duration_ms": r.duration_ms,
    } for r in list_runs(request.app.state.database, user_id)]
    return request.app.state.templates.TemplateResponse(
        request=request, name="pages/runs.html", context={"runs": runs},
    )


@router.get("/runs/{run_id}", include_in_schema=False)
def run_detail_page(request: Request, run_id: str, user_id: int = Depends(current_user_id)):
    loaded = load_run(request.app.state.database, user_id, run_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="실행 기록을 찾을 수 없습니다")
    run, *events = run_records(*loaded)
    summary = {
        **run, "started": _kst(run["started_at"]), "ended": _kst(run["ended_at"]),
        "end_label": END_LABELS.get(run["end_reason"], run["end_reason"]),
    }
    return request.app.state.templates.TemplateResponse(
        request=request, name="pages/run_detail.html",
        context={"run": summary, "events": _event_rows(run, events), "counts": _counts(events)},
    )


@router.get("/runs/{run_id}/export", include_in_schema=False)
def export_run(request: Request, run_id: str, user_id: int = Depends(current_user_id)):
    exported = export_jsonl(request.app.state.database, user_id, run_id)
    if exported is None:
        raise HTTPException(status_code=404, detail="실행 기록을 찾을 수 없습니다")
    filename, content = exported
    return Response(content, media_type="application/x-ndjson; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
