"""로그인 없이 열리는 공개 페이지: 앱 소개·개인정보처리방침·서비스 약관(Issue #82).

Google Auth Platform 브랜딩의 홈페이지·개인정보처리방침·서비스 약관 링크가 이 경로를 가리킨다.
앱 이름은 OAuth 동의 화면과 같은 `APP_NAME`을 쓴다.
"""

from fastapi import APIRouter, Request

from app.web import templates

router = APIRouter()

APP_NAME = "Gmail 견적 도우미"
POLICY_DATE = "2026-11-11"
REPO_ISSUES = "https://github.com/encore-ai-campus/aio-03-p2-team3/issues"


def _page(request: Request, name: str):
    return templates.TemplateResponse(request=request, name=f"pages/{name}.html", context={
        "app_name": APP_NAME, "policy_date": POLICY_DATE, "repo_issues": REPO_ISSUES,
    })


@router.get("/about", include_in_schema=False)
def about(request: Request):
    return _page(request, "about")


@router.get("/privacy", include_in_schema=False)
def privacy(request: Request):
    return _page(request, "privacy")


@router.get("/terms", include_in_schema=False)
def terms(request: Request):
    return _page(request, "terms")
