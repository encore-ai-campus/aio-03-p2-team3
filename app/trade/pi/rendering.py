"""PI 출력은 검증된 문서의 계좌·회사 스냅숏과 공통 PDF/XLSX 구현을 사용한다."""
from app.trade.common.rendering import render_approved_files


def render_pi_files(payload, branding):
    if payload["document_type"] != "PI":
        raise ValueError("PI 출력에 다른 문서를 사용할 수 없습니다")
    return render_approved_files(payload, branding)
