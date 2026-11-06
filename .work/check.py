#!/usr/bin/env python3
"""작업 레포 규칙 검사.

사용: python3 .work/check.py   (레포 안 어느 폴더에서 실행해도 된다)
      python3 .work/check.py --pr [본문 파일]   PR 본문의 '읽은 파일'·'최신 흐름 갱신' 칸 검사(CI 작업 pr-check).
          CI에서는 GITHUB_EVENT_PATH의 PR 본문과 base를 쓴다. 로컬에서는 본문을 파일로 주고 base는 origin/main(없으면 main).
결과: 문제가 없으면 0, 오류가 있으면 1로 끝난다. 경고와 참고는 실패로 치지 않는다.
claude-github-setup(커밋 9c45959)의 check.py를 한 번 복사해 이 레포에 맞췄고, 이제 이 레포가 소유한다.
테스트(uv run pytest)는 부르지 않는다. 표준 라이브러리만 써서 uv·네트워크 없이 돈다. 테스트는 따로 돌린다(AGENTS.md '확인 명령').
출처: 검사 항목 [Past work: setup · Claude proposal] · PR 전에 검사를 통과시키는 방식 [Past work: aio3]
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REQUIRED = ("AGENTS.md", ".work/RULES.md", ".work/TASK.md", ".work/STATUS.md", "docs/PROJECT_CONTEXT.md",
            ".github/pull_request_template.md")
CONTEXT = "docs/PROJECT_CONTEXT.md"
STATUS_SECTIONS = ("지금 할 일", "대기", "보류", "최근 완료", "이전 기록 요약")
RECENT_LIMIT = 10
TASK_RULES_SECTION = "이 레포의 규칙"
TASK_MAP_SECTION = "파일 지도"
# 출처 태그. 여럿이면 [Request · Claude proposal]처럼 가운뎃점으로 잇는다.
TAG_ONE = r"(?:Request|Claude proposal|Past work:[^\]·]+)"
TAG_RE = re.compile(r"\[" + TAG_ONE + r"(?:\s*·\s*" + TAG_ONE + r")*\]")
ITEM_RE = re.compile(r"^(?:- |\d+\. )(.*)$")
UPDATED_RE = re.compile(r"마지막 갱신: \d{4}-\d{2}-\d{2}")
# 읽음 확인 코드: AGENTS.md '먼저 읽을 것' 세 파일에 한 줄씩 둔다. PR 본문 '읽은 파일' 칸에 같은 값을 적는다 [Claude proposal]
CODE_FILES = (".work/RULES.md", ".work/TASK.md", CONTEXT)
CODE_RE = re.compile(r"^읽음 확인 코드: ([A-Z]+-[A-Z0-9]{4})\s*$")
PR_READ_SECTION = "읽은 파일"
PR_CONTEXT_SECTION = "최신 흐름 갱신"

# 세팅 단계 작업(공통 규칙 8절): 다음 단계 안내와 작업 흐름
TODO_SECTION = "지금 할 일"
GUIDE_FIELD_RE = re.compile(r"^\s+- (명령어|첨부|읽을 파일|읽지 않을 파일|만들 파일|도구|작업량):(.*)$")
GUIDE_REQUIRED = ("도구", "작업량")
GUIDE_MEASURED = (("read", "읽을 파일"), ("attach", "첨부"), ("make", "만들 파일"), ("tools", "도구"))
WORKLOAD_RE = re.compile(r"약\s*(?P<x>\d+(?:\.\d+)?)\s*KB[^/]*/\s*기준\s*(?P<y>\d+(?:\.\d+)?)\s*KB")
WORKLOAD_SLACK_KB = 2
BACKTICK_RE = re.compile(r"`([^`]+)`")
FLOW_STEP_RE = re.compile(r"\d+(?:-\d+)*단계(\s|$)")
FLOW_SPLIT_RE = re.compile(r"으?로 나눔")  # 나눈 단계의 묶음 제목(공통 규칙 8절 '작업 배분량 검토')
FLOW_FIELDS = ("할 일", "읽을 것", "만들 것", "섞지 않을 것", "도구")
FLOW_FIELD_RE = re.compile(r"^- (" + "|".join(FLOW_FIELDS) + "):")
NO_REFERENCE_RE = re.compile(r"참고하지\s*(말|않)")
_measure = None

# AI가 자동으로 읽는 파일들. 규칙은 AGENTS.md가 가리키는 파일에만 둔다(AGENTS.md). 막지는 않고 경고만 한다.
ENTRY = "AGENTS.md"
AUTOLOAD_NAMES = {"CLAUDE.md", "CLAUDE.local.md", ".mcp.json"}
AUTOLOAD_DIR = ".claude"

SECRET_FILE_RE = re.compile(r"(^|/)\.env$|\.local\.[^/]+$")
SECRET_PATTERNS = (
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "Anthropic API 키"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"), "GitHub 토큰"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS 키"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "Google API 키"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "개인 키"),
)


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []

    def print(self) -> int:
        for message in self.notes:
            print(f"참고  {message}")
        for message in self.warnings:
            print(f"경고  {message}")
        for message in self.errors:
            print(f"오류  {message}")
        if self.errors:
            print(f"\n검사 실패: 오류 {len(self.errors)}개, 경고 {len(self.warnings)}개")
            return 1
        print(f"검사 통과 (경고 {len(self.warnings)}개)")
        return 0


def repo_files(root: Path, report: Report) -> list[str]:
    """커밋될 파일 목록: 추적 중인 파일 + .gitignore에 걸리지 않은 새 파일."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root, capture_output=True, check=True,
        ).stdout.decode("utf-8")
        return sorted({p for p in out.split("\0") if p and (root / p).is_file()})
    except (OSError, subprocess.CalledProcessError):
        report.warnings.append("git을 쓸 수 없어 폴더 전체를 검사한다(.gitignore가 적용되지 않음)")
        return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                      if p.is_file() and ".git" not in p.relative_to(root).parts)


def read_lines(root: Path, rel: str, report: Report) -> list[str] | None:
    path = root / rel
    if not path.is_file():
        report.errors.append(f"{rel}: 파일이 없다")
        return None
    return path.read_text(encoding="utf-8-sig").splitlines()


def strip_comments(lines: list[str]) -> list[str]:
    """HTML 주석을 지운 줄 목록. 줄 번호는 그대로 둔다."""
    out: list[str] = []
    in_comment = False
    for line in lines:
        if in_comment:
            if "-->" not in line:
                out.append("")
                continue
            line, in_comment = line.split("-->", 1)[1], False
        line = re.sub(r"<!--.*?-->", "", line)
        if "<!--" in line:
            line, in_comment = line.split("<!--", 1)[0], True
        out.append(line)
    return out


def sections(lines: list[str]) -> dict[str, list[tuple[int, str]]]:
    """'## 제목' 아래 줄들을 (줄 번호, 내용)으로 모은다."""
    found: dict[str, list[tuple[int, str]]] = {}
    current = None
    for no, line in enumerate(lines, 1):
        m = re.match(r"##\s+(.+?)\s*$", line)
        if m:
            current = m.group(1)
            found[current] = []
        elif current is not None:
            found[current].append((no, line))
    return found


def rule_items(numbered: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """규칙 항목(맨 앞이 '- ' 또는 '1. ')만 고른다. 들여쓴 하위 항목, 코드 블록, '(아직 없음)' 같은 자리표시자는 뺀다."""
    items: list[tuple[int, str]] = []
    in_code = False
    for no, line in numbered:
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code or line.startswith((" ", "\t")):
            continue
        m = ITEM_RE.match(line)
        if m and not m.group(1).startswith("("):
            items.append((no, m.group(1)))
    return items


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub("", text)).strip().rstrip(".")


def check_rules(rel: str, items: list[tuple[int, str]], report: Report, seen: dict[str, str]) -> None:
    """출처 태그(없으면 경고)와 같은 규칙 중복(오류)을 본다. seen에는 앞서 본 규칙이 쌓인다."""
    for no, text in items:
        if not TAG_RE.search(text):
            report.warnings.append(f"{rel}:{no}: 출처 태그가 없다 ([Request] / [Past work: …] / [Claude proposal])")
        key = normalize(text)
        if key in seen:
            report.errors.append(f"{rel}:{no}: 같은 규칙이 이미 있다({seen[key]}) — 공통 규칙 4절대로 하나로 합친다")
        else:
            seen[key] = f"{rel}:{no}"


def check_map(rel: str, numbered: list[tuple[int, str]], files: list[str], report: Report) -> None:
    """파일 지도 각 줄의 맨 앞 경로가 레포에 있는지, 레포의 모든 파일이 지도 줄로 덮이는지 본다."""
    known = set(files) | {"/".join(f.split("/")[:i]) for f in files for i in range(1, f.count("/") + 1)}
    paths: set[str] = set()
    folders: list[str] = []
    for no, line in numbered:
        m = re.match(r"- `([^`]+)`", line)
        if not m:
            continue
        path = m.group(1)
        if path.endswith("/"):
            folders.append(path)
        else:
            paths.add(path)
        if path.rstrip("/") not in known:
            report.errors.append(f"{rel}:{no}: 파일 지도의 `{path}`이(가) 레포에 없다")
    # 역검사: 정확한 경로 줄이나 `/`로 끝나는 폴더 줄로 덮여야 한다 [Claude proposal]
    for f in files:
        if f not in paths and not any(f.startswith(d) for d in folders):
            report.errors.append(f"{rel}: `{f}`이(가) 파일 지도에 없다(경로 줄이나 `/`로 끝나는 폴더 줄을 더한다, RULES 5절 2번)")


def read_code(lines: list[str]) -> list[str]:
    return [m.group(1) for line in lines if (m := CODE_RE.match(line))]


def check_codes(lines: dict[str, list[str] | None], report: Report) -> None:
    """먼저 읽을 세 파일에 읽음 확인 코드 줄이 하나씩 있는지 본다."""
    for rel in CODE_FILES:
        if lines.get(rel) is not None and len(read_code(lines[rel])) != 1:
            report.errors.append(f"{rel}: '읽음 확인 코드: <약칭>-<영숫자 4자>' 줄이 하나여야 한다")


def check_status(rel: str, lines: list[str], report: Report) -> None:
    if not any(re.fullmatch(r"마지막 갱신: \d{4}-\d{2}-\d{2}\s*", line) for line in lines):
        report.errors.append(f"{rel}: '마지막 갱신: YYYY-MM-DD' 줄이 없다")
    found = sections(strip_comments(lines))
    for name in STATUS_SECTIONS:
        if name not in found:
            report.errors.append(f"{rel}: '## {name}' 절이 없다")
    recent = [line for _, line in found.get("최근 완료", []) if line.startswith("- ")]
    if len(recent) > RECENT_LIMIT:
        report.errors.append(f"{rel}: '최근 완료'가 {len(recent)}개다 — {RECENT_LIMIT}개가 넘으면 "
                             "오래된 것부터 '이전 기록 요약'에 월별 한 줄로 합친다")


def load_measure(report: Report):
    """같은 폴더의 measure.py를 파일 경로로 불러온다(안내의 작업량을 같은 방법으로 다시 재려고). 없으면 오류를 남기고 None."""
    global _measure
    if _measure is None:
        path = Path(__file__).resolve().parent / "measure.py"
        if not path.is_file():
            report.errors.append(".work/measure.py: 파일이 없어 안내의 작업량을 다시 재지 못했다")
            return None
        sys.dont_write_bytecode = True  # .work/에 파이썬 캐시가 생기지 않게 한다
        spec = importlib.util.spec_from_file_location("task_measure", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _measure = module
    return _measure


def warn_no_reference(rel: str, numbered: list[tuple[int, str]], report: Report) -> None:
    """'참고하지 말/않'은 막지 못한다: 대화에 들어간 내용은 참고하지 말라고 해도 결과에 섞인다."""
    for no, line in numbered:
        if NO_REFERENCE_RE.search(line):
            report.warnings.append(f"{rel}:{no}: '참고하지 말/않'이 있다 — 대화에 들어간 내용은 그렇게 적어도 섞인다. "
                                   "넣지 않을 것은 '읽지 않을 파일'·'섞지 않을 것'으로 보내 아예 읽지 않게 한다")


def guide_items(numbered: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
    """'지금 할 일'을 항목(맨 앞 '- ' 줄과 그 아래 들여 쓴 줄)으로 묶는다."""
    items: list[list[tuple[int, str]]] = []
    for no, line in numbered:
        if line.startswith("- "):
            items.append([(no, line)])
        elif items and line.startswith((" ", "\t")) and line.strip():
            items[-1].append((no, line))
    return items


def check_context(rel: str, lines: list[str], report: Report) -> None:
    """최신 흐름의 '## ' 절마다 '마지막 갱신: YYYY-MM-DD' 줄이 있는지 본다(공통 규칙 5절 1번)."""
    for title, body in sections(strip_comments(lines)).items():
        if not any(UPDATED_RE.search(line) for _, line in body):
            report.errors.append(f"{rel}: '## {title}' 절에 '마지막 갱신: YYYY-MM-DD' 줄이 없다 — 공통 규칙 5절 1번")


def check_guides(root: Path, rel: str, lines: list[str], report: Report,
                 start: tuple[str, ...] | None = None) -> None:
    """STATUS '지금 할 일'의 다음 단계 안내(들여 쓴 '- 명령어:' 줄이 있는 항목)를 본다(공통 규칙 8절 '단계를 마칠 때').
    작업량은 안내의 백틱 항목으로 measure.py를 다시 불러 잰다. start는 시작할 때 읽는 파일로,
    없으면 measure.py의 기본값(START_FILES: AGENTS.md가 시작할 때 읽게 하는 파일)을 쓴다."""
    todo = sections(strip_comments(lines)).get(TODO_SECTION, [])
    warn_no_reference(rel, todo, report)
    for item in guide_items(todo):
        fields: dict[str, tuple[int, str]] = {}
        for no, line in item[1:]:
            m = GUIDE_FIELD_RE.match(line)
            if m:
                fields[m.group(1)] = (no, m.group(2))
        if "명령어" not in fields:
            continue
        head = f"{rel}:{item[0][0]}"
        missing = [name for name in GUIDE_REQUIRED if name not in fields]
        for name in missing:
            report.errors.append(f"{head}: 다음 단계 안내에 '- {name}:' 줄이 없다 — 공통 규칙 8절 '단계를 마칠 때' 1번 형식대로 적는다")
        if missing:
            continue
        no, text = fields["작업량"]
        m = WORKLOAD_RE.search(text)
        if not m:
            report.errors.append(f"{rel}:{no}: 작업량이 '약 X KB / 기준 Y KB' 형식이 아니다")
            continue
        written, limit = float(m.group("x")), float(m.group("y"))
        measure = load_measure(report)
        if measure is None:
            return
        args = {key: BACKTICK_RE.findall(fields[name][1]) if name in fields else [] for key, name in GUIDE_MEASURED}
        try:
            result = measure.measure_groups(root, start=tuple(start or measure.START_FILES), **args)
        except measure.Fail as exc:
            report.errors.append(f"{head}: 안내의 작업량을 다시 재지 못했다 — {exc}")
            continue
        again = measure.kb(result.known)
        if abs(result.known / measure.KB - written) > WORKLOAD_SLACK_KB:
            report.errors.append(f"{rel}:{no}: 작업량이 약 {written:g} KB로 적혀 있는데 다시 재면 약 {again} KB다"
                                 f"({WORKLOAD_SLACK_KB} KB 넘게 다름) — 안내의 항목으로 다시 재서 고친다")
        if result.verdict(limit)[1] == measure.OVER and not any("배분량 검토" in line for _, line in item):
            report.errors.append(f"{head}: 다시 잰 작업량 약 {again} KB가 기준 {limit:g} KB를 넘는데 '배분량 검토'가 적혀 있지 않다 "
                                 "— 작업 배분량 검토로 나눈다")


def check_flow(rel: str, lines: list[str], report: Report) -> None:
    """작업 흐름의 '## N단계'(N은 3, 3-1 꼴) 절마다 할 일·읽을 것·만들 것·섞지 않을 것·도구 줄이 있는지 본다.
    'N-1, N-2로 나눔'이 붙은 묶음 제목은 하위 단계가 그 줄을 가지므로 건너뛴다."""
    clean = strip_comments(lines)
    warn_no_reference(rel, list(enumerate(clean, 1)), report)
    for title, body in sections(clean).items():
        if not FLOW_STEP_RE.match(title) or FLOW_SPLIT_RE.search(title):
            continue
        have = {m.group(1) for _, line in body if (m := FLOW_FIELD_RE.match(line))}
        missing = ", ".join(f"'- {name}:'" for name in FLOW_FIELDS if name not in have)
        if missing:
            report.errors.append(f"{rel}: '## {title}' 절에 {missing} 줄이 없다 — 공통 규칙 8절 '작업 흐름' 형식대로 적는다")


def check_flows(root: Path, map_lines: list[tuple[int, str]], report: Report) -> None:
    """TASK.md 파일 지도에서 '작업 흐름'이 적힌 줄의 파일을 검사한다. 없는 파일은 check_map이 알린다."""
    for _, line in map_lines:
        m = re.match(r"- `([^`]+)`", line)
        if m and "작업 흐름" in line and (root / m.group(1)).is_file():
            check_flow(m.group(1), (root / m.group(1)).read_text(encoding="utf-8-sig").splitlines(), report)


def check_no_autoload(files: list[str], report: Report) -> None:
    """자동으로 읽히는 파일이 있으면 경고한다. 규칙이 AGENTS.md 밖에 생기면 AI마다 다른 규칙을 읽는다."""
    for rel in files:
        parts = rel.split("/")
        if parts[-1] == ENTRY and rel != ENTRY:
            report.warnings.append(f"{rel}: 루트 말고는 {ENTRY}를 두지 않는다 — Codex가 그 폴더에서 자동으로 읽는다")
        if parts[-1] in AUTOLOAD_NAMES:
            report.warnings.append(f"{rel}: AI가 자동으로 읽는 파일이다 — 규칙은 {ENTRY}가 가리키는 파일에만 둔다({ENTRY})")
        if AUTOLOAD_DIR in parts[:-1]:
            report.warnings.append(f"{rel}: .claude/ 폴더는 Claude가 자동으로 읽는다 — 규칙은 {ENTRY}가 가리키는 파일에만 둔다({ENTRY})")


def check_secrets(root: Path, files: list[str], report: Report) -> None:
    for rel in files:
        if SECRET_FILE_RE.search(rel):
            report.errors.append(f"{rel}: 비밀값·PC별 설정 파일은 올리지 않는다 (.gitignore 확인)")
        path = root / rel
        try:
            if path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # 바이너리 파일은 건너뛴다
        for no, line in enumerate(text.splitlines(), 1):
            for pattern, label in SECRET_PATTERNS:
                if pattern.search(line):
                    report.errors.append(f"{rel}:{no}: {label}로 보이는 값이 있다")


def run(root: Path) -> Report:
    report = Report()
    files = repo_files(root, report)
    check_no_autoload(files, report)

    lines = {rel: read_lines(root, rel, report) for rel in REQUIRED}
    rules, task, status = lines[".work/RULES.md"], lines[".work/TASK.md"], lines[".work/STATUS.md"]
    seen: dict[str, str] = {}
    if rules is not None:
        check_rules(".work/RULES.md", rule_items(list(enumerate(strip_comments(rules), 1))), report, seen)
    if task is not None:
        found = sections(strip_comments(task))
        for name in (TASK_RULES_SECTION, TASK_MAP_SECTION):
            if name not in found:
                report.errors.append(f".work/TASK.md: '## {name}' 절이 없다")
        check_rules(".work/TASK.md", rule_items(found.get(TASK_RULES_SECTION, [])), report, seen)
        check_map(".work/TASK.md", found.get(TASK_MAP_SECTION, []), files, report)
        check_flows(root, found.get(TASK_MAP_SECTION, []), report)
    if rules is not None and task is not None:
        report.notes.append(f"작업 시작 때 읽는 규칙: RULES.md {len(rules)}줄 + TASK.md {len(task)}줄 "
                            f"= {len(rules) + len(task)}줄")
    if status is not None:
        check_status(".work/STATUS.md", status, report)
        check_guides(root, ".work/STATUS.md", status, report)
    if lines[CONTEXT] is not None:
        check_context(CONTEXT, lines[CONTEXT], report)
    check_codes(lines, report)

    check_secrets(root, files, report)
    return report


def pr_sections(body: str) -> dict[str, str]:
    """PR 본문을 '## 제목'별 글로 나눈다. 주석(<!-- -->)은 뺀다."""
    found: dict[str, str] = {}
    name = None
    for line in re.sub(r"<!--.*?-->", "", body, flags=re.S).splitlines():
        m = re.match(r"##\s+(.+?)\s*$", line)
        if m:
            name = m.group(1)
            found[name] = ""
        elif name is not None:
            found[name] += line + "\n"
    return found


def changed_files(root: Path, base: str, report: Report) -> list[str] | None:
    try:
        out = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"],
                             cwd=root, capture_output=True, check=True, text=True).stdout
        return [p for p in out.splitlines() if p]
    except (OSError, subprocess.CalledProcessError) as e:
        report.errors.append(f"`git diff {base}...HEAD`를 못 돌렸다(CI는 checkout fetch-depth: 0): {e}")
        return None


def local_base(root: Path) -> str:
    for ref in ("origin/main", "main"):
        if subprocess.run(["git", "rev-parse", "--verify", "-q", ref], cwd=root,
                          capture_output=True).returncode == 0:
            return ref
    return "origin/main"


def run_pr(root: Path, body: str, base: str) -> Report:
    """PR 본문의 '읽은 파일'·'최신 흐름 갱신' 칸을 본다(RULES 5절 4번, AGENTS.md 'Codex가 꼭 할 일' 4번)."""
    report = Report()
    found = pr_sections(body or "")
    read = found.get(PR_READ_SECTION)
    if read is None:
        report.errors.append(f"PR 본문: '## {PR_READ_SECTION}' 칸이 없다(PR 양식)")
    else:
        for rel in CODE_FILES:
            path = root / rel
            codes = read_code(path.read_text(encoding="utf-8-sig").splitlines()) if path.is_file() else []
            if len(codes) != 1:
                report.errors.append(f"{rel}: 읽음 확인 코드 줄을 찾지 못했다")
            elif not re.search(r"(?<![A-Z0-9-])" + re.escape(codes[0]) + r"(?![A-Z0-9])", read):
                report.errors.append(f"PR 본문 '{PR_READ_SECTION}': {rel}의 읽음 확인 코드가 없거나 다르다"
                                     "(파일을 끝까지 읽고 그 줄 값을 적는다)")
    context = found.get(PR_CONTEXT_SECTION)
    changed = changed_files(root, base, report)
    if context is None:
        report.errors.append(f"PR 본문: '## {PR_CONTEXT_SECTION}' 칸이 없다(PR 양식)")
    elif changed is not None:
        edited = re.search(r"고친 절:\s*\S", context)
        skipped = re.search(r"해당 없음\s*[—-]+\s*\S", context)
        if CONTEXT in changed and not edited:
            report.errors.append(f"PR 본문 '{PR_CONTEXT_SECTION}': {CONTEXT}를 고쳤으니 `고친 절: <번호>`를 적는다")
        if CONTEXT not in changed and not skipped:
            report.errors.append(f"PR 본문 '{PR_CONTEXT_SECTION}': {CONTEXT}가 바뀌지 않았다. 바꾼 영역의 절을 고치거나"
                                 " `해당 없음 — <이유>`를 적는다(RULES 5절 1번)")
    if not report.errors:
        report.notes.append(f"PR 본문 검사: base {base}, 바뀐 파일 {len(changed or [])}개")
    return report


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    args = sys.argv[1:]
    if args and args[0] == "--pr":
        event = os.environ.get("GITHUB_EVENT_PATH")
        if len(args) > 1:
            body, base = Path(args[1]).read_text(encoding="utf-8-sig"), local_base(root)
        elif event:
            pr = json.loads(Path(event).read_text(encoding="utf-8")).get("pull_request") or {}
            body, base = pr.get("body") or "", (pr.get("base") or {}).get("sha", "origin/main")
        else:
            print("오류  --pr: 본문 파일을 주거나 GITHUB_EVENT_PATH(GitHub Actions pull_request)에서 돌린다")
            return 1
        return run_pr(root, body, base).print()
    return run(root).print()


if __name__ == "__main__":
    sys.exit(main())
