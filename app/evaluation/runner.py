"""시험 실행기(계획 17절): 저장된 시험 메일을 그래프에 넣어 성찰 끔/켬으로 같은 입력·기준으로 돌린다.

- 실행마다 `start_run(mode="test", reflection_enabled=끔/켬, scenario=시나리오 키)`를 부른다. 반복마다 새 메일·스레드 ID를
  써서 앞 실행의 단기 기억이 다음 실행에 섞이지 않게 하고, 같은 반복 번호의 끔/켬을 번갈아 돌린다.
- 승인 발송 단계가 있는 시나리오(발송 성공이 장기 기억을 남김)는 다른 시나리오를 모두 돌린 뒤 맨 끝에 돌린다.
- 가짜 LLM 실행(`mode="fake"`)은 시나리오의 준비된 응답만 쓰고, 실제 API 실행(`mode="real"`)은 주입 목록 말고는
  실제 OpenAI가 답한다. 주입한 호출은 실행 기록에 `detail.injected: true`로 표시한다(실제 API 결과와 구분).
- 끝나면 실행마다 판정(`metrics.judge_run`)하고 성찰 끔/켬의 4개 지표(`metrics.compute_metrics`)를 낸다.

명령줄:
  uv run python -m app.evaluation.runner --fake [--repeat 3] [--scenario 키 …] [--out 결과.json]
  uv run python -m app.evaluation.runner --real (--user-email 시험계정 | --user-id N) [--repeat 3]
      [--export-dir docs/test-records] [--gmail-search [검색어] | --gmail-source 메일ID:스레드ID …] [--out 결과.json]
- `--gmail-search`: 승인 발송 시나리오에 쓸 실제 메일을 시험 계정의 Gmail에서 찾는다(기본 검색어
  `DEFAULT_GMAIL_SEARCH`). 제목·본문이 시나리오와 같은 받은 메일 가운데 앞 실행에 쓰지 않은 것을 오래된 순으로 쓴다.
"""

import argparse
from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from uuid import uuid4

from sqlalchemy import func, select

from app.clients.gmail import decode_message
from app.config import LIMITS
from app.db.engine import Database
from app.db.models import ReplyCandidate, Run, User
from app.evaluation.injection import InjectedSendFailure, ScenarioBackend, mark_injected, mark_injected_sends
from app.evaluation.metrics import compute_metrics, judge_run, render_markdown
from app.evaluation.scenarios import SCENARIOS, Scenario
from app.graph.run import start_run
from app.llm import client
from app.runlog.export import export_jsonl
from app.services.approval import send_approved_candidate
from app.services.auth import get_access_token

DEFAULT_GMAIL_SEARCH = "in:inbox subject:evalsend newer_than:30d"
GMAIL_SEARCH_MAX = 500


def resolve_user(database: Database, *, user_id: int | None = None, user_email: str | None = None) -> int:
    """시험 사용자 id. 이메일로 찾으면 대소문자를 가리지 않는다. 없으면 ValueError."""
    with database.session() as session:
        if user_email is not None:
            found = session.scalars(select(User.id).where(func.lower(User.email) == user_email.strip().lower())).all()
            if len(found) != 1:
                raise ValueError("그 이메일로 로그인한 사용자가 없습니다. 먼저 로컬 서버에서 그 계정으로 로그인하세요")
            return found[0]
        if user_id is None or session.get(User, user_id) is None:
            raise ValueError("등록되지 않은 사용자입니다")
        return user_id


def _same_text(expected: str, actual: str) -> bool:
    return " ".join(expected.split()) in " ".join(actual.split())


def find_gmail_sources(database: Database, access, user_id: int, scenario: Scenario, *, limit: int,
                       query: str = DEFAULT_GMAIL_SEARCH) -> tuple[list[tuple[str, str]], dict]:
    """시험 계정 Gmail에서 승인 발송 시나리오에 쓸 실제 메일 (메일ID, 스레드ID)를 오래된 순으로 `limit`개까지 찾는다.

    검색(users.messages.list의 q, gmail.readonly 범위) → 앞 실행(`runs.message_id`)에 쓴 메일 빼기 → 메일을 읽어
    받은 메일이고 제목이 같고 본문에 시나리오 본문이 들어 있는 것만 쓴다. 메일 내용은 돌려주지 않는다.
    """
    with database.session() as session:
        own_email = session.get(User, user_id).email
    try:
        gmail = access.google.gmail(get_access_token(access, user_id))
        refs, page = [], None
        while len(refs) < GMAIL_SEARCH_MAX:
            response = gmail.users().messages().list(
                userId="me", q=query, maxResults=100, pageToken=page,
            ).execute(num_retries=LIMITS["GMAIL_MAX_RETRIES"])
            refs += response.get("messages", [])
            page = response.get("nextPageToken")
            if not page:
                break
    except Exception as error:
        # 오류 원문에는 토큰·주소가 섞일 수 있어 종류만 알린다.
        raise RuntimeError(f"Gmail 검색 실패 ({type(error).__name__})") from None
    ids = [ref["id"] for ref in refs]
    with database.session() as session:
        used = set(session.scalars(select(Run.message_id).where(Run.user_id == user_id, Run.message_id.in_(ids))))
    sources, mismatched = [], 0
    for ref in reversed(refs):   # 검색 결과는 최신 순이라 뒤집어 오래된 메일부터 쓴다
        if len(sources) >= limit:
            break
        if ref["id"] in used:
            continue
        try:
            mail = decode_message(access.google.get_message(gmail, ref["id"]), own_email,
                                  lambda attachment_id, mid=ref["id"]: access.google.get_attachment(gmail, mid, attachment_id))
        except Exception as error:
            raise RuntimeError(f"Gmail 메일 읽기 실패 ({type(error).__name__})") from None
        if (mail["direction"] != "in" or mail["subject"].strip() != scenario.subject
                or not _same_text(scenario.body, mail["body_text"])):
            mismatched += 1
            continue
        sources.append((ref["id"], ref["threadId"]))
    return sources, {"query": query, "found": len(refs), "already_used": len(used),
                     "mismatched": mismatched, "selected": len(sources), "needed": limit}


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
                    reason = "승인 발송 단계에 Gmail 연결이 필요합니다(실제 실행은 --gmail-search)"
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
    kind.add_argument("--real", action="store_true", help="실제 OpenAI(주입 목록 말고), DATABASE_URL의 DB")
    who = parser.add_mutually_exclusive_group()
    who.add_argument("--user-email", help="실제 실행에 쓸 시험 계정 이메일(로컬 서버에서 로그인한 계정)")
    who.add_argument("--user-id", type=int, help="실제 실행에 쓸 시험 사용자 id")
    parser.add_argument("--repeat", type=int, default=3, help="시나리오·성찰 설정마다 반복 횟수(기본 3)")
    parser.add_argument("--scenario", action="append", help="돌릴 시나리오 키(여러 번 줄 수 있음, 없으면 전부)")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--gmail-search", nargs="?", const=DEFAULT_GMAIL_SEARCH, metavar="검색어",
                        help=f"승인 발송 시나리오에 쓸 실제 메일을 Gmail에서 찾음(기본 '{DEFAULT_GMAIL_SEARCH}')")
    source.add_argument("--gmail-source", action="append", type=_parse_source, default=[],
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

    access, search_report = None, None
    if args.fake:
        if args.user_email or args.user_id or args.gmail_search:
            parser.error("--fake에는 --user-email·--user-id·--gmail-search를 쓰지 않습니다")
        database = Database("sqlite://")
        database.create_tables()
        with database.session() as session:
            session.add(User(id=1, google_sub="eval-fake", email="tester@example.invalid"))
        user_id = 1
        sources = list(args.gmail_source)
    else:
        if args.user_email is None and args.user_id is None:
            parser.error("--real에는 --user-email(또는 --user-id)이 필요합니다")
        from app.clients.gmail import GoogleClient
        from app.config import get_settings
        from app.db.engine import get_database
        from app.services.auth import GoogleAccess, make_cipher
        settings = get_settings()
        database = get_database(settings)
        try:
            user_id = resolve_user(database, user_id=args.user_id, user_email=args.user_email)
        except ValueError as error:
            parser.error(str(error))
        sources = list(args.gmail_source)
        approval = [s for s in chosen if s.needs_access]
        if (args.gmail_source or args.gmail_search) and approval:
            access = GoogleAccess(database, GoogleClient(settings), make_cipher(settings), settings.gmail_pubsub_topic)
        if args.gmail_search and access is not None:
            for scenario in approval:
                found, report = find_gmail_sources(database, access, user_id, scenario,
                                                   limit=args.repeat * 2, query=args.gmail_search)
                sources += found
                search_report = {**(search_report or {}), scenario.key: report}
                sys.stdout.write(f"Gmail 검색({scenario.key}): 찾음 {report['found']}통, 앞 실행에 씀 "
                                 f"{report['already_used']}통, 내용 다름 {report['mismatched']}통 → "
                                 f"{report['selected']}/{report['needed']}통 사용\n")

    result = run_suite(database, user_id, scenarios=chosen, repeat=args.repeat,
                       mode="fake" if args.fake else "real", access=access,
                       gmail_sources=sources, export_dir=args.export_dir)
    if search_report:
        result["gmail_search"] = search_report
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
