from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.web.routes.pages import APP_NAME


def test_public_pages_open_without_login():
    with TestClient(create_app(Settings(database_url="sqlite://"))) as client:
        for path in ["/about", "/privacy", "/terms"]:
            page = client.get(path, follow_redirects=False)
            assert page.status_code == 200, path
            assert page.headers["content-type"].startswith("text/html")
            assert APP_NAME in page.text
        about = client.get("/about").text
        assert 'href="/privacy"' in about and 'href="/terms"' in about and 'href="/login"' in about
        privacy = client.get("/privacy").text
        for word in ["gmail.readonly", "gmail.send", "Gemini", "Render", "암호화", "삭제"]:
            assert word in privacy, word
        login = client.get("/login").text
        for path in ["/about", "/privacy", "/terms"]:
            assert f'href="{path}"' in login
