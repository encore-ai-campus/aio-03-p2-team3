"""실행 환경 확인 테스트(세팅 3-2-3단계).

기능 테스트가 생기기 전에 `uv run pytest`가 통과하도록 둔다.
Python 버전과 pyproject.toml의 패키지를 불러올 수 있는지만 본다. 외부 API는 부르지 않는다.
"""

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_python_version():
    assert sys.version_info[:2] == (3, 12)


@pytest.mark.parametrize(
    "module",
    [
        "langgraph",
        "langchain_google_genai",
        "googleapiclient",
        "google.auth",
        "google_auth_oauthlib",
        "httpx",
        "dotenv",
    ],
)
def test_packages_import(module):
    importlib.import_module(module)


def test_env_example_has_no_values():
    """.env.example에는 이름만 두고 값은 넣지 않는다(RULES 3절)."""
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, _, value = line.partition("=")
            assert name and value == "", f"값이 들어 있음: {name}"
