from pathlib import Path

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


def test_app_does_not_initialize_a_shared_llm_even_with_server_key(monkeypatch):
    from app.llm import client as llm
    settings = Settings(database_url="sqlite://", openai_api_key="fake-openai-key", openai_model="gpt-fake")
    def backend(*args, **kwargs):
        raise AssertionError("서버 공용 키를 사용하면 안 됩니다")

    monkeypatch.setattr(llm, "_backend_for_settings", backend)
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert app.state.llm is None
