from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_home_and_local_assets(monkeypatch):
    from app import main
    from app.db.engine import get_database

    graph_builds = []
    original = main.get_graph
    def count_graph_build():
        graph_builds.append(True)
        return original()
    monkeypatch.setattr(main, "get_graph", count_graph_build)
    app = create_app(Settings(database_url="sqlite://"))
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        home = client.get("/")
        assert home.status_code == 200 and home.url.path == "/inbox"
        assert '<html lang="ko">' in home.text and "Gmail 견적 도우미" in home.text
        assert 'href="/login"' in home.text
        for path in ["css/tokens.css", "css/app.css", "js/htmx.min.js"]:
            assert client.get(f"/static/{path}").status_code == 200
        assert 'https://' not in home.text
        assert graph_builds == [True]
        assert get_database(Settings(database_url="sqlite://")) is app.state.database
        assert app.state.llm is None


def test_every_template_compiles():
    from jinja2 import Environment, FileSystemLoader
    directory = Path(__file__).parents[1] / "app/web/templates"
    templates = Environment(loader=FileSystemLoader(directory))
    for name in templates.list_templates():
        templates.get_template(name)


@pytest.mark.parametrize(("path", "heading", "required_text"), [
    ("/about", "Gmail 견적 도우미", ["수업 과제용 시연", "답장 후보 2~3개", "승인해야만", "견적서"]),
    ("/privacy", "개인정보처리방침", [
        "gmail.readonly", "gmail.send", "이메일 주소", "Render Postgres", "암호화",
        "Gemini 무료 등급", "Google 제품 개선", "과제 종료 뒤 삭제", "타사 액세스", "GitHub Issue",
    ]),
    ("/terms", "서비스 약관", ["수업 과제용 시연", "실제 업무", "실제 개인정보", "보증하지", "중단될 수"]),
])
def test_public_pages_without_login(path, heading, required_text):
    # OAuth·LLM 키나 로그인 쿠키가 없어도 리디렉션 없이 읽을 수 있어야 한다.
    with TestClient(create_app(Settings(database_url="sqlite://"))) as client:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert f"<h1>{heading}</h1>" in response.text
        assert "테스트용 Gmail" in response.text
        for text in required_text:
            assert text in response.text


@pytest.mark.parametrize(("path", "links"), [
    ("/about", ["/privacy", "/terms"]),
    ("/login", ["/about", "/privacy", "/terms"]),
])
def test_public_page_links(path, links):
    with TestClient(create_app(Settings(database_url="sqlite://"))) as client:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200
        for link in links:
            assert f'href="{link}"' in response.text
