# PDF 한글 글꼴

`NanumGothic-Regular.ttf`는 Google Fonts의 원본 파일이다. 수정하지 않았다.

- 원본: https://github.com/google/fonts/blob/main/ofl/nanumgothic/NanumGothic-Regular.ttf
- SHA-256: `76f45ef4a6bcff344c837c95a7dcc26e017e38b5846d5ae0cdcb5b86be2e2d31`
- 저작권·라이선스: 같은 폴더 `OFL.txt` 원문. SIL OFL 1.1은 소프트웨어와 함께 재배포·PDF 포함을 허용한다. 글꼴 자체만 판매하지 않으며 저작권·라이선스를 함께 배포한다.

PDF는 `fpdf2==2.9.0`이 메모리에서 만든다. 공식 문서는 Python 3.10 이상, 적은 Python 의존성(Pillow·fonttools), 유니코드 TTF 부분 포함을 안내한다. Render의 Python 3.12에서 `uv sync --locked`로 설치하며 별도 시스템 글꼴·브라우저·PDF 변환 프로그램을 설치하지 않는다. 기본 TTF 한글 출력에는 선택 기능인 HarfBuzz 문자 조형을 켜지 않는다.

- 공식 기능·의존성: https://py-pdf.github.io/fpdf2/ (2026-11-10 확인)
- 공식 글꼴 포함 방법: https://py-pdf.github.io/fpdf2/Unicode.html (`add_font` → `set_font`, 2026-11-10 확인)
- 설치 확인: PyPI Linux CPython 3.12 wheel 의존성으로 설치하고 한글 추출·글꼴 포함 테스트로 검증한다. 실제 Render 재배포 확인은 사람의 API·배포 시험 단계에서 한다.
