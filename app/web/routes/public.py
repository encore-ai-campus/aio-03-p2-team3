"""로그인 없이 읽는 서비스 소개·정책 페이지(CONTRACT 9절, Issue #82)."""

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/about", include_in_schema=False)
def about_page(request: Request):
    return request.app.state.templates.TemplateResponse(request=request, name="pages/about.html")


@router.get("/privacy", include_in_schema=False)
def privacy_page(request: Request):
    return request.app.state.templates.TemplateResponse(request=request, name="pages/privacy.html")


@router.get("/terms", include_in_schema=False)
def terms_page(request: Request):
    return request.app.state.templates.TemplateResponse(request=request, name="pages/terms.html")
