#!/usr/bin/env python3
"""작업량 재기(공통 규칙 8절). 대화 하나나 자동 실행 1회가 맡는 일의 양을 기준과 견준다.

사용: python3 .work/measure.py [--read 항목 …] [--attach 항목 …] [--make 항목 …] [--tools 항목 …] [--limit KB]
      python3 .work/measure.py --outline <파일>            절마다 줄 범위와 크기
      python3 .work/measure.py --show '<파일>#<절 제목>'    그 절만 출력('<파일>:<시작>-<끝>'도 된다)
항목: 파일·폴더 경로, '경로#절 제목', '경로:시작-끝'(줄 범위), '이름=KB'(레포 밖 파일이나 만들 파일의 크기), '이름=?'(크기 모름)
--read는 읽을 파일(레포 밖 파일은 '이름=KB'), --attach는 첨부할 파일, --make는 만들 파일이다. 상대 경로는 레포 맨 위 폴더 기준이다.
--tools는 실행 중 생기는 양(도구 결과)이다: '종류=횟수'(TOOL_KB 표의 1회 크기), '종류=횟수x크기'(1회 KB를 직접 준다,
  표에 없는 종류도), '종류=?'(횟수 모름). 예: --tools 웹검색=16 MCP=6 서브에이전트=1 스크립트=5
시작할 때 읽는 파일(AGENTS.md, .work/RULES.md, .work/TASK.md, .work/STATUS.md, docs/PROJECT_CONTEXT.md)은 늘 더한다. 자동 실행 1회를 잴 때는 --start에 프롬프트 파일을 준다.
크기만 내고 파일 내용은 출력하지 않는다(--show 빼고). 단위는 KB(1024바이트)다.
텍스트가 아닌 파일(pdf, docx, zip, .skill, 이미지 등)은 KB가 담긴 내용과 달라 합에서 빼고 크기 모름으로 센다.
끝 코드: 적당 0, 기준 초과 2, 판단 보류(크기 모름) 3, 오류 1.
재는 일은 measure_groups()가 출력 없이 하고, check.py도 이 함수로 다시 잰다.
claude-github-setup(커밋 9c45959)에서 한 번 복사해 고쳤고, 이제 이 레포가 소유한다(공통 규칙 머리말). 고칠 때는 이 레포에서 고친다.
출처: 첨부 파일 크기의 합으로 판단 [Request] · 실행 중 생기는 양 [Request] · KB 단위 [Request] · 시작할 때 읽는 파일 포함 [Request] · 발췌 [Request] · 나머지 [Claude proposal]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple, Sequence

DEFAULT_LIMIT_KB = 100.0  # 계획 작업량 기준. 실제는 대개 1.1~1.4배(공통 규칙 8절 5번)
KB = 1024
# AGENTS.md가 시작할 때 읽게 하는 파일 모두(진입 파일, 공통 규칙, 레포 규칙, 세팅 진행기록, 최신 흐름)
START_FILES = ("AGENTS.md", ".work/RULES.md", ".work/TASK.md", ".work/STATUS.md", "docs/PROJECT_CONTEXT.md")
# 도구 1회 결과 크기(KB). 2026-11-06 '최근 완료' 기록을 보고 그대로 두기로 정했다(넘은 까닭은 대부분 횟수가 늘어난 것).
# 사용 한도·자동 요약에 걸리거나 1회 크기가 크게 다르면 기록과 사용자 의견을 보고 고친다(공통 규칙 8절).
# 레포 연결: add_repo 결과 1회 약 4KB(2026-11-05 4-1단계에서 잼, 2026-11-06 7-2단계에서도 약 4KB).
TOOL_KB = {"웹검색": 15.0, "웹페이지": 5.0, "MCP": 5.0, "서브에이전트": 5.0, "스크립트": 3.0, "레포 연결": 4.0}
TOOL_RE = re.compile(r"^(?P<kind>[^=]+)=(?:(?P<count>\d+)(?:[xX×](?P<size>\d+(?:\.\d+)?))?|(?P<unknown>\?))$")
TOOLS_TITLE = "실행 중 생기는 양"
NOT_TEXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".hwp", ".hwpx", ".zip", ".skill", ".7z",
            ".gz", ".tar", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".mp3", ".mp4", ".wav", ".mov"}
SKIP_DIRS = {".git", "__pycache__", "node_modules"}
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
SIZE_RE = re.compile(r"^(.+)=(\d+(?:\.\d+)?|\?)$")
RANGE_RE = re.compile(r"^(.+):(\d+)-(\d+)$")
OK, ERROR, OVER, UNKNOWN = 0, 1, 2, 3


class Fail(Exception):
    """사용자에게 그대로 보여 줄 오류."""


def kb(size: float) -> str:
    return f"{size / KB:.1f}"


def text_lines(path: Path) -> list[str] | None:
    """텍스트 파일이면 줄 목록(줄바꿈 포함)을, 아니면 None을 돌려준다."""
    if path.suffix.lower() in NOT_TEXT:
        return None
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    return text.splitlines(keepends=True)


def size_of(lines: list[str]) -> int:
    return sum(len(line.encode("utf-8")) for line in lines)


def headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """(줄 번호, 제목 수준, 제목). 코드 블록 안의 '#' 줄은 뺀다."""
    found: list[tuple[int, int, str]] = []
    fence = False
    for no, line in enumerate(lines, 1):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        m = None if fence else HEADING_RE.match(line.rstrip("\r\n"))
        if m:
            found.append((no, len(m.group(1)), m.group(2)))
    return found


def sections(lines: list[str]) -> list[tuple[int, int, int, str]]:
    """(시작 줄, 끝 줄, 제목 수준, 제목). 한 절은 다음에 오는 같거나 높은 수준의 제목 앞까지다(하위 절 포함)."""
    marks = headings(lines)
    out = []
    for i, (start, level, title) in enumerate(marks):
        end = next((no - 1 for no, lv, _ in marks[i + 1:] if lv <= level), len(lines))
        out.append((start, end, level, title))
    return out


def clean_title(title: str) -> str:
    return title.strip().lstrip("#").strip()


def find_section(lines: list[str], title: str, label: str) -> tuple[int, int]:
    want = clean_title(title)
    matches = [(start, end) for start, end, _, t in sections(lines) if t == want]
    if not matches:
        raise Fail(f"{label}: 제목이 '{want}'인 절이 없다(--outline으로 제목을 확인한다)")
    if len(matches) > 1:
        starts = ", ".join(f"{start}줄" for start, _ in matches)
        raise Fail(f"{label}: 제목이 '{want}'인 절이 여러 개다({starts}) — '경로:시작-끝'으로 준다")
    return matches[0]


def resolve(root: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else root / path


def excerpt(root: Path, raw: str) -> tuple[str, list[str], int, int]:
    """'경로#절 제목'이나 '경로:시작-끝'을 (경로, 그 파일의 줄 목록, 시작 줄, 끝 줄)로 푼다."""
    m = RANGE_RE.match(raw)
    if m and resolve(root, m.group(1)).is_file():
        rel, start, end = m.group(1), int(m.group(2)), int(m.group(3))
        lines = read_text_or_fail(resolve(root, rel), rel)
        if not 1 <= start <= end <= len(lines):
            raise Fail(f"{raw}: 줄 범위가 파일({len(lines)}줄)을 벗어난다")
        return rel, lines, start, end
    if "#" in raw:
        rel, title = raw.split("#", 1)
        if resolve(root, rel).is_file():
            lines = read_text_or_fail(resolve(root, rel), rel)
            start, end = find_section(lines, title, raw)
            return rel, lines, start, end
    raise Fail(f"{raw}: 파일이 없다")


def read_text_or_fail(path: Path, label: str) -> list[str]:
    lines = text_lines(path)
    if lines is None:
        raise Fail(f"{label}: 텍스트 파일이 아니다")
    return lines


def measure_item(root: Path, raw: str, allow_given: bool) -> list[tuple[int | None, str, str]]:
    """항목 하나를 (바이트 또는 None, 표시 이름, 덧붙임) 줄들로 잰다."""
    path = resolve(root, raw)
    if path.is_file():
        lines = text_lines(path)
        if lines is None:
            return [(None, raw, "텍스트가 아님 — 텍스트로 뽑아 잰 크기를 '이름=KB'로 넣는다")]
        return [(size_of(lines), raw, "")]
    if path.is_dir():
        total, count, rows = 0, 0, []
        for item in sorted(p for p in path.rglob("*") if p.is_file()):
            if set(item.relative_to(path).parts) & SKIP_DIRS:
                continue
            lines = text_lines(item)
            if lines is None:
                rows.append((None, f"{raw.rstrip('/')}/{item.relative_to(path).as_posix()}",
                             "텍스트가 아님 — 텍스트로 뽑아 잰 크기를 '이름=KB'로 넣는다"))
                continue
            total, count = total + size_of(lines), count + 1
        return [(total, raw, f"텍스트 파일 {count}개")] + rows
    m = SIZE_RE.match(raw)
    if allow_given and m:
        if m.group(2) == "?":
            return [(None, m.group(1), "크기 모름")]
        return [(round(float(m.group(2)) * KB), m.group(1), "적은 값")]
    rel, lines, start, end = excerpt(root, raw)
    return [(size_of(lines[start - 1:end]), raw, f"{start}~{end}줄")]


def measure_tool(raw: str) -> tuple[int | None, str, str]:
    """도구 항목 하나('종류=횟수', '종류=횟수x크기', '종류=?')를 (바이트 또는 None, 표시 이름, 덧붙임)으로 잰다."""
    m = TOOL_RE.match(raw)
    if not m:
        raise Fail(f"{raw}: 도구 항목은 '종류=횟수', '종류=횟수x크기'(1회 KB), '종류=?'(횟수 모름)로 준다")
    kind = m.group("kind").strip()
    if m.group("unknown"):
        return None, kind, "횟수 모름"
    count = int(m.group("count"))
    if m.group("size") is not None:
        size_kb, note = float(m.group("size")), "적은 크기"
    elif kind in TOOL_KB:
        size_kb, note = TOOL_KB[kind], ""
    else:
        raise Fail(f"{raw}: '{kind}'는 표({', '.join(TOOL_KB)})에 없다 — 1회 크기를 '종류=횟수x크기'(KB)로 준다")
    return round(count * size_kb * KB), f"{kind} {count}회 × {size_kb:g} KB", note


class Measured(NamedTuple):
    """재기 결과. groups는 (묶음 제목, [(바이트 또는 None, 표시 이름, 덧붙임), …]) 목록이다.
    dataclass를 쓰지 않는다: check.py가 파일 경로로 불러 sys.modules에 없을 때 dataclass는 깨진다."""
    groups: list[tuple[str, list[tuple[int | None, str, str]]]]
    known: int       # 크기를 아는 것의 합(실행 중 생기는 양 포함), 바이트
    unknown: int     # 크기 모름 개수
    tool_bytes: int  # known 가운데 실행 중 생기는 양, 바이트
    has_tools: bool  # --tools 항목이 있었는지

    def verdict(self, limit_kb: float) -> tuple[str, int]:
        if self.known > limit_kb * KB:
            return "기준 초과", OVER
        if self.unknown:
            return "판단 보류(크기 모름)", UNKNOWN
        return "적당", OK

    def total_text(self) -> str:
        """'약 X KB(실행 중 Y KB 포함) + 크기 모름 N개'. 실행 중 표시는 --tools가 있을 때만 붙인다."""
        text = f"약 {kb(self.known)} KB"
        if self.has_tools:
            text += f"(실행 중 {kb(self.tool_bytes)} KB 포함)"
        return text + (f" + 크기 모름 {self.unknown}개" if self.unknown else "")


def measure_groups(root: Path, read: Sequence[str] = (), attach: Sequence[str] = (), make: Sequence[str] = (),
                   tools: Sequence[str] = (), start: Sequence[str] = START_FILES) -> Measured:
    """출력 없이 잰다. 잘못된 항목은 Fail로 낸다. check.py도 이 함수로 안내의 작업량을 다시 잰다."""
    missing = [rel for rel in start if not resolve(root, rel).is_file()]
    if missing:
        raise Fail(f"시작할 때 읽는 파일이 없다: {', '.join(missing)} — 레포 밖에서 부르면 --root, 위치가 다르면 --start로 준다")
    groups = []
    for title, items, allow_given in (("시작할 때 읽는 파일", start, False), ("읽을 파일", read, True),
                                      ("첨부할 파일", attach, True), ("만들 파일", make, True)):
        if items:
            groups.append((title, [r for raw in items for r in measure_item(root, raw, allow_given)]))
    tool_rows = [measure_tool(raw) for raw in tools]
    if tool_rows:
        groups.append((TOOLS_TITLE, tool_rows))
    sizes = [size for _, rows in groups for size, _, _ in rows]
    return Measured(groups=groups, known=sum(s for s in sizes if s is not None),
                    unknown=sum(1 for s in sizes if s is None),
                    tool_bytes=sum(s for s, _, _ in tool_rows if s is not None), has_tools=bool(tool_rows))


def row(size: int | None, label: str, note: str) -> str:
    amount = f"{kb(size):>7} KB" if size is not None else "      ? KB"
    return f"  {amount}  {label}" + (f"  ({note})" if note else "")


def report(result: Measured, limit_kb: float) -> int:
    print(f"작업량 — 기준 {limit_kb:g} KB")
    for title, rows in result.groups:
        print(title)
        for size, label, note in rows:
            print(row(size, label, note))
    verdict, code = result.verdict(limit_kb)
    percent = result.known / (limit_kb * KB) * 100
    print(f"합계: {result.total_text()} / 기준 {limit_kb:g} KB ({percent:.0f}%) → {verdict}")
    return code


def outline(root: Path, raw: str) -> int:
    lines = read_text_or_fail(resolve(root, raw), raw)
    print(f"{raw} — {len(lines)}줄, {kb(size_of(lines))} KB")
    marks = sections(lines)
    if not marks:
        print("  제목(#)이 없다 — '경로:시작-끝'(줄 범위)으로 나눈다")
        return OK
    if marks[0][0] > 1:
        print(f"  {kb(size_of(lines[:marks[0][0] - 1])):>7} KB  1~{marks[0][0] - 1}줄  (첫 제목 앞)")
    for start, end, level, title in marks:
        print(f"  {kb(size_of(lines[start - 1:end])):>7} KB  {start}~{end}줄  {'  ' * (level - 1)}{'#' * level} {title}")
    return OK


def show(root: Path, raw: str) -> int:
    rel, lines, start, end = excerpt(root, raw)
    print(f"[{rel} {start}~{end}줄, {kb(size_of(lines[start - 1:end]))} KB]")
    sys.stdout.write("".join(lines[start - 1:end]))
    if lines[end - 1:end] and not lines[end - 1].endswith(("\n", "\r")):
        sys.stdout.write("\n")
    return OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="작업량 재기(공통 규칙 8절)")
    parser.add_argument("--read", action="extend", nargs="+", default=[], metavar="항목", help="읽을 파일(레포 밖 파일은 '이름=KB')")
    parser.add_argument("--attach", action="extend", nargs="+", default=[], metavar="항목", help="첨부할 파일")
    parser.add_argument("--make", action="extend", nargs="+", default=[], metavar="항목", help="만들 파일")
    parser.add_argument("--tools", action="extend", nargs="+", default=[], metavar="항목",
                        help="실행 중 생기는 양: '종류=횟수', '종류=횟수x크기'(1회 KB), '종류=?'")
    parser.add_argument("--limit", type=float, default=DEFAULT_LIMIT_KB, metavar="KB", help="기준(기본 100)")
    parser.add_argument("--start", nargs="+", default=list(START_FILES), metavar="파일", help="시작할 때 읽는 파일")
    parser.add_argument("--root", help="레포 맨 위 폴더(기본: 이 파일이 있는 .work의 위)")
    parser.add_argument("--outline", metavar="파일", help="절마다 줄 범위와 크기를 보여 준다")
    parser.add_argument("--show", metavar="항목", help="'경로#절 제목'이나 '경로:시작-끝'만 출력한다")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    try:
        if args.outline:
            return outline(root, args.outline)
        if args.show:
            return show(root, args.show)
        result = measure_groups(root, read=args.read, attach=args.attach, make=args.make, tools=args.tools,
                                start=args.start)
        return report(result, args.limit)
    except Fail as exc:
        print(f"오류  {exc}")
        return ERROR


if __name__ == "__main__":
    sys.exit(main())
