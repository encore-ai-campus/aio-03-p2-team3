import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.web.routes.pages import APP_NAME


@pytest.mark.parametrize(("path", "heading", "required_text"), [
    ("/about", APP_NAME, ["수업 과제", "테스트용 Gmail", "답장 후보 2~3개", "승인해야만", "견적서"]),
    ("/privacy", "개인정보처리방침", [
        "gmail.readonly", "gmail.send", "이메일 주소", "Render", "PostgreSQL", "암호화",
        "OpenAI API", "API 데이터", "과제 종료 뒤 삭제", "타사 앱", "GitHub Issue",
    ]),
    ("/terms", "서비스 약관", ["수업 과제", "테스트용 Gmail", "실제 업무", "실제 개인정보", "보증 없이", "중단될 수"]),
])
def test_public_pages_open_without_login(database_url, path, heading, required_text):
    # OAuth·LLM 키나 로그인 쿠키가 없어도 리디렉션 없이 읽을 수 있어야 한다.
    with TestClient(create_app(Settings(database_url=database_url))) as client:
        page = client.get(path, follow_redirects=False)
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        assert APP_NAME in page.text
        assert f"<h1>{heading}</h1>" in page.text
        for text in required_text:
            assert text in page.text


@pytest.mark.parametrize(("path", "links"), [
    ("/about", ["/privacy", "/terms", "/login"]),
    ("/login", ["/about", "/privacy", "/terms"]),
])
def test_public_links_in_page_content(database_url, path, links):
    with TestClient(create_app(Settings(database_url=database_url))) as client:
        page = client.get(path, follow_redirects=False)
        assert page.status_code == 200
        # 공통 푸터 링크만으로 통과하지 않게 각 화면의 본문을 확인한다.
        content = page.text.split('<main class="shell">', 1)[1].split("</main>", 1)[0]
        for link in links:
            assert f'href="{link}"' in content
