"""CI가 실행 코드 변경을 문서 변경으로 잘못 생략하지 않는지 실제 git 이력으로 확인한다."""

import json
import subprocess

import pytest

from scripts.ci_scope import documentation_only, main, needs_tests


@pytest.mark.parametrize("paths", [
    ["README.md", "docs/plans/example.md"],
    [".work/TASK.md", "AGENTS.md", ".github/pull_request_template.md"],
    ["Team/README.md", "Presentation/README.md"],
])
def test_known_documents_can_skip_tests(paths):
    assert documentation_only(paths)


@pytest.mark.parametrize("path", [
    "app/main.py", "tests/test_auth.py", "frontend/src/App.jsx", "frontend/package-lock.json",
    "scripts/render-build.sh", "scripts/ci_scope.py", ".github/workflows/rules-check.yml",
    ".github/workflows/pr-check.yml", "pyproject.toml", "uv.lock", ".python-version",
    ".env.example", "render.yaml", "docs/example.py", "unknown/README.md", "app/prompt.md",
    "docs/TEST_REPORT.md",
])
def test_code_configuration_and_tested_report_require_tests(path):
    assert not documentation_only(["docs/plans/example.md", path])


def test_empty_diff_is_not_assumed_to_be_documentation():
    assert not documentation_only([])


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


def commit(repo):
    git(repo, "add", ".")
    git(repo, "-c", "user.name=CI Test", "-c", "user.email=ci@example.invalid",
        "commit", "-qm", "test change")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def history(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "README.md").write_text("original", encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app/code.py").write_text("original", encoding="utf-8")
    return tmp_path, commit(tmp_path)


def pr(base, head):
    return {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}


def test_document_pr_uses_merge_base_but_push_checks_the_entire_change(history):
    repo, original = history
    (repo / "README.md").write_text("updated", encoding="utf-8")
    document_head = commit(repo)
    git(repo, "checkout", "--detach", original)
    (repo / "app/code.py").write_text("new code on main", encoding="utf-8")
    main_head = commit(repo)

    assert not needs_tests(pr(main_head, document_head), "pull_request", cwd=repo)
    assert needs_tests({"before": main_head, "after": document_head}, "push", cwd=repo)
    assert not needs_tests({"before": original, "after": document_head}, "push", cwd=repo)


def test_renaming_code_into_docs_still_requires_tests(history):
    repo, base = history
    (repo / "docs").mkdir()
    (repo / "app/code.py").rename(repo / "docs/example.md")
    head = commit(repo)
    assert needs_tests(pr(base, head), "pull_request", cwd=repo)


def test_deleting_code_still_requires_tests(history):
    repo, base = history
    (repo / "app/code.py").unlink()
    head = commit(repo)
    assert needs_tests(pr(base, head), "pull_request", cwd=repo)


@pytest.mark.parametrize("event,event_name", [
    ({}, "pull_request"),
    ({"before": "missing", "after": "missing"}, "push"),
    ({"before": "0" * 40, "after": "f" * 40}, "push"),
    (None, "push"),
    ({}, "unknown_event"),
])
def test_missing_history_or_event_never_skips_tests(history, event, event_name):
    repo, _ = history
    assert needs_tests(event, event_name, cwd=repo)


def test_event_file_writes_an_explicit_documentation_result(history, monkeypatch):
    repo, base = history
    (repo / "README.md").write_text("updated", encoding="utf-8")
    head = commit(repo)
    event_path, output = repo / "event.json", repo / "output.txt"
    event_path.write_text(json.dumps(pr(base, head)), encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    main()
    assert output.read_text(encoding="utf-8") == "run_tests=false\n"


def test_broken_event_file_falls_back_to_full_tests(tmp_path, monkeypatch):
    event_path, output = tmp_path / "event.json", tmp_path / "output.txt"
    event_path.write_text("invalid json", encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    main()
    assert output.read_text(encoding="utf-8") == "run_tests=true\n"
