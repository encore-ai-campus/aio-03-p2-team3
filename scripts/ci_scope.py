"""문서만 바뀌었는지 확인한다. 모르는 경로·조회 실패는 전체 테스트를 실행한다."""

import json
import os
from pathlib import Path
import re
import subprocess


DOC_FILES = {"README.md", "AGENTS.md", ".github/pull_request_template.md"}
DOC_DIRS = ("docs/", "Team/", "Presentation/", ".work/")
# 이 보고서 내용은 test_evaluation.py가 직접 검증하므로 문서 생략 대상에서 제외한다.
TESTED_DOCS = {"docs/TEST_REPORT.md"}


def documentation_only(paths):
    return bool(paths) and all(
        path not in TESTED_DOCS and (
            path in DOC_FILES or (path.startswith(DOC_DIRS) and path.endswith(".md"))
        ) for path in paths
    )


def changed_paths(base, head, *, pull_request=False, cwd=None):
    for revision in (base, head):
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40,64}", revision):
            raise ValueError("비교할 commit SHA가 없습니다")
    revisions = [f"{base}...{head}"] if pull_request else [base, head]
    # rename의 원래 코드 경로도 포함한다. 코드→문서 이동을 문서 변경으로 오인하지 않는다.
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", "-z", *revisions, "--"],
        cwd=cwd, check=True, capture_output=True, timeout=30,
    )
    return result.stdout.decode("utf-8").rstrip("\0").split("\0") if result.stdout else []


def needs_tests(event, event_name, *, cwd=None):
    try:
        if event_name == "pull_request":
            base, head = event["pull_request"]["base"]["sha"], event["pull_request"]["head"]["sha"]
        elif event_name == "push":
            base, head = event["before"], event["after"]
        else:
            return True
        return not documentation_only(changed_paths(
            base, head, pull_request=event_name == "pull_request", cwd=cwd,
        ))
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        return True


def main():
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        run_tests = needs_tests(event, os.environ.get("GITHUB_EVENT_NAME"))
    except (KeyError, ValueError, OSError):
        run_tests = True
    value = str(run_tests).lower()
    print("전체 테스트 실행" if run_tests else "문서만 변경: Python·Windows 테스트 생략")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"run_tests={value}\n")


if __name__ == "__main__":
    main()
