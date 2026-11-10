"""시험 실행기(계획 17절): 저장된 시험 메일을 그래프에 넣어 성찰 끔/켬으로 같은 입력·기준으로 돌린다.

- 실행마다 `start_run(mode="test", reflection_enabled=끔/켬, scenario=시나리오 키)`를 부른다. 반복마다 새 메일·스레드 ID를
  써서 앞 실행의 단기 기억이 다음 실행에 섞이지 않게 하고, 같은 반복 번호의 끔/켬을 번갈아 돌린다.
- 승인 발송 단계가 있는 시나리오(발송 성공이 장기 기억을 남김)는 다른 시나리오를 모두 돌린 뒤 맨 끝에 돌린다.
- 가짜 LLM 실행(`mode="fake"`)은 시나리오의 준비된 응답만 쓰고, 실제 API 실행(`mode="real"`)은 주입 목록 말고는
  실제 Gemini가 답한다. 주입한 호출은 실행 기록에 `detail.injected: true`로 표시한다(실제 API 결과와 구분).
- 끝나면 실행마다 판정(`metrics.judge_run`)하고 성찰 끔/켬의 4개 지표(`metrics.compute_metrics`)를 낸다.

명령줄:
  uv run python -m app.evaluation.runner --fake [--repeat 3] [--scenario 키 …] [--out 결과.json]
  uv run python -m app.evaluation.runner --real --user-id N [--repeat 3] [--export-dir docs/test-records]
      [--gmail-source 메일ID:스레드ID …] [--out 결과.json]
"""

import argparse
from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from uuid import uuid4

from sqlalchemy import select

from app.db.engine import Database
from app.db.models import ReplyCandidate, User
from app.evaluation.injection import InjectedSendFailure, ScenarioBackend, mark_injected, mark_injected_sends
from app.evaluation.metrics import compute_metrics, judge_run, render_markdown
from app.evaluation.scenarios import SCENARIOS, Scenario
from app.graph.run import start_run
from app.llm import client
from app.runlog.export import export_jsonl
from app.services.approval import send_approved_candidate


def _fake_script(scenario: Scenario, repetition: int) -> dict:
    if isinstance(scenario.fake, list):
        return scenario.fake[repetition % len(scenario.fake)]
    return scenario.fake


def build_email(scenario: Scenario, to_addr: str, message_id: str, thread_id: str) -> dict:
    return {
        "gmail_message_id": message_id, "thread_id": thread_id, "rfc_message_id": f"<{message_id}@example.invalid>",
        "from_addr": scenario.sender, "from_name": None, "to_addrs": [to_addr],
        "subject": scenario.subject, "body_text": scenario.body,
        "received_at": datetime.now(UTC).isoformat(), "direction": "in",
    }


def _approve(database, user_id, run_id, scenario, access):
    """이 실행의 첫 후보를 승인 발송한다. 결과 키 목록과 시도별 고의 실패 여부를 돌려준다."""
    if access.database is not database:
        raise ValueError("access.database와 실행기 DB가 같아야 합니다")
    with database.session() as session:
        candidate_id = session.scalar(select(ReplyCandidate.id).where(
            ReplyCandidate.run_id == run_id, ReplyCandidate.user_id == user_id, ReplyCandidate.kind != "quote",
        ).order_by(ReplyCandidate.id))
    if candidate_id is None:
        return [], []
    google = InjectedSendFailure(access.google, scenario.send_failures)
    injected_access = replace(access, google=google)
    outcomes, injected = [], []
    for _ in scenario.expect.approval:
        before = len(google.sends)
        outcomes.append(send_approved_candidate(user_id, candidate_id, access=injected_access).outcome)
        injected.append(len(google.sends) > before and google.sends[-1])
        if outcomes[-1] == "sent":
            break
    return outcomes, injected


def run_once(database: Database, user_id: int, scenario: Scenario, *, reflection_enabled: bool, repetition: int,
             mode: str = "fake", access=None, real=None, gmail_source: tuple[str, str] | None = None,
             export_dir: Path | None = None) -> dict:
    with database.session() as session:
        user = session.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise ValueError("등록되지 않은 사용자입니다")
        to_addr = user.email
    suffix = f"{scenario.key}-{'on' if reflection_enabled else 'off'}-{repetition}-{uuid4().hex[:8]}"
    message_id, thread_id = gmail_source or (f"eval-{suffix}", f"eval-thread-{suffix}")
    backend = ScenarioBackend(
        inject=scenario.inject, fake=None if mode == "real" else _fake_script(scenario, repetition),
        real=(real or client.get_backend) if mode == "real" else None,
    )
    with client.use_backend(backend):
        result = start_run(user_id=user_id, email=build_email(scenario, to_addr, message_id, thread_id),
                           mode="test", reflection_enabled=reflection_enabled, scenario=scenario.key,
                           database=database)
    run_id = result["run_id"]
    injected = mark_injected(database, run_id, backend.calls)
    outcomes = []
    if scenario.needs_access:
        outcomes, sends = _approve(database, user_id, run_id, scenario, access)
        injected += mark_injected_sends(database, run_id, sends)
    judgment = judge_run(database, run_id, scenario, outcomes)
    # 실행 기록으로 판정한 값이 그래프 상태(`tools_called`·`call_retries`·`reflection_retries`)와 같은지 함께 남긴다.
    state_matches = ([r["tool"] for r in result["tools_called"]] == judgment["tools_called"]
                     and result["call_retries"] == judgment["call_retries"]
                     and result["reflection_retries"] == judgment["reflection_retries"])
    judgment.update(repetition=repetition, approval=outcomes, injected_events=injected, state_matches=state_matches,
                    llm_calls={"prepared": sum(k == "prepared" for _, k in backend.calls),
                               "failure": sum(k == "failure" for _, k in backend.calls),
                               "real": sum(k is None for _, k in backend.calls)})
    if export_dir is not None:
        exported = export_jsonl(database, user_id, run_id)
        if exported is not None:
            export_dir.mkdir(parents=True, exist_ok=True)
            (export_dir / exported[0]).write_text(exported[1], encoding="utf-8")
            judgment["record_file"] = exported[0]
    return judgment


def run_suite(database: Database, user_id: int, *, scenarios=SCENARIOS, repeat: int = 3, mode: str = "fake",
              access=None, real=None, gmail_sources=(), export_dir: Path | None = None) -> dict:
    """시나리오마다 `repeat`번씩 성찰 끔/켬으로 돌리고 판정·지표를 돌려준다."""
    if mode not in {"fake", "real"}:
        raise ValueError("mode는 fake 또는 real이어야 합니다")
    if repeat < 1:
        raise ValueError("repeat는 1 이상이어야 합니다")
    ordered = [s for s in scenarios if not s.needs_access] + [s for s in scenarios if s.needs_access]
    sources = list(gmail_sources)
    judgments, skipped = [], []
    for scenario in ordered:
        for repetition in range(repeat):
            for reflection_enabled in (False, True):
                source, reason = None, None
                if scenario.needs_access and access is None:
                    reason = "승인 발송 단계에 Gmail 연결(access)이 필요합니다"
                elif scenario.needs_access and mode == "real":
                    if sources:
                        source = sources.pop(0)
                    else:
                        reason = "실제 Gmail 시험 메일 ID가 필요합니다(--gmail-source)"
                if reason:
                    skipped.append({"scenario": scenario.key, "repetition": repetition,
                                    "reflection_enabled": reflection_enabled, "reason": reason})
                    continue
                judgments.append(run_once(
                    database, user_id, scenario, reflection_enabled=reflection_enabled, repetition=repetition,
                    mode=mode, access=access, real=real, gmail_source=source, export_dir=export_dir,
                ))
    return {
        "mode": mode, "repeat": repeat, "finished_at": datetime.now(UTC).isoformat(),
        "scenarios": [{"key": s.key, "category": s.category, "title": s.title,
                       "tools": sorted(s.expect.tools), "end_reason": s.expect.end_reason} for s in ordered],
        "judgments": judgments, "skipped": skipped, "metrics": compute_metrics(judgments),
    }


def _parse_source(value: str) -> tuple[str, str]:
    message_id, sep, thread_id = value.partition(":")
    if not sep or not message_id or not thread_id:
        raise argparse.ArgumentTypeError("메일ID:스레드ID 형식이어야 합니다")
    return message_id, thread_id


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="시험 실행기: 같은 입력을 성찰 끔/켬으로 돌려 4개 지표를 계산한다")
    kind = parser.add_mutually_exclusive_group(required=True)
    kind.add_argument("--fake", action="store_true", help="가짜 LLM(준비된 응답), 메모리 DB")
    kind.add_argument("--real", action="store_true", help="실제 Gemini(주입 목록 말고), DATABASE_URL의 DB")
    parser.add_argument("--user-id", type=int, help="실제 실행에 쓸 시험 사용자 id(로그인한 테스트 계정)")
    parser.add_argument("--repeat", type=int, default=3, help="시나리오·성찰 설정마다 반복 횟수(기본 3)")
    parser.add_argument("--scenario", action="append", help="돌릴 시나리오 키(여러 번 줄 수 있음, 없으면 전부)")
    parser.add_argument("--gmail-source", action="append", type=_parse_source, default=[],
                        help="승인 발송 시나리오에 쓸 실제 시험 메일 '메일ID:스레드ID'(실행 하나에 하나)")
    parser.add_argument("--export-dir", type=Path, help="실행마다 기록 파일(.jsonl)을 쓸 폴더")
    parser.add_argument("--out", type=Path, help="판정·지표 결과 JSON 파일")
    args = parser.parse_args(argv)

    chosen = SCENARIOS
    if args.scenario:
        known = {s.key: s for s in SCENARIOS}
        unknown = [k for k in args.scenario if k not in known]
        if unknown:
            parser.error(f"모르는 시나리오: {', '.join(unknown)}")
        chosen = tuple(known[k] for k in args.scenario)

    access = None
    if args.fake:
        database = Database("sqlite://")
        database.create_tables()
        with database.session() as session:
            session.add(User(id=1, google_sub="eval-fake", email="tester@example.invalid"))
        user_id = 1
    else:
        if args.user_id is None:
            parser.error("--real에는 --user-id가 필요합니다")
        from app.clients.gmail import GoogleClient
        from app.config import get_settings
        from app.db.engine import get_database
        from app.services.auth import GoogleAccess, make_cipher
        settings = get_settings()
        database = get_database(settings)
        user_id = args.user_id
        if args.gmail_source:
            access = GoogleAccess(database, GoogleClient(settings), make_cipher(settings), settings.gmail_pubsub_topic)

    result = run_suite(database, user_id, scenarios=chosen, repeat=args.repeat,
                       mode="fake" if args.fake else "real", access=access,
                       gmail_sources=args.gmail_source, export_dir=args.export_dir)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.write(render_markdown(result["metrics"]))
    for item in result["skipped"]:
        sys.stdout.write(f"건너뜀: {item['scenario']} 반복 {item['repetition']} "
                         f"성찰 {'켬' if item['reflection_enabled'] else '끔'} — {item['reason']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
