# reference/kekorea — KE KOREA 원본 사본 (이식용, 읽기 전용)

KE KOREA 무역서류(PI/PO/CI/PL) 프로그램을 이 서비스로 옮길 때 보는 원본 사본이다. 팀원은 원본 레포(`doomdiver100T/ai-agents`, Private) 접근 없이 이 폴더만 보고 이식한다. 이식 계획은 `docs/plans/kekorea-port.md`, 이식 규칙은 `.work/TASK.md` '이 레포의 규칙'.

- 원본: `doomdiver100T/ai-agents` `main` 커밋 `8d397a1`(2026-11-10)의 `AI AGENTS/KE_KOREA_CO_LTD/Quotation_KEKOREA/`. 원작자 임석원. [Request]
- 사용 허락: 임석원을 통해 회사에서 받았다(팀 과제·발표 사용). [Request]
- 이 폴더는 고치지 않고, 앱(`app/`)에서 import하지 않는다. pytest는 `testpaths = ["tests"]`라 이 폴더의 테스트를 수집하지 않는다. [Claude proposal]

## 들어 있는 것

| 경로 | 무엇 | 이식 묶음 |
|---|---|---|
| `Quotation_KEKOREA/agent/extractor.py`·`review_fields.py`·`attachments.py` | LLM 추출(OpenAI 요청 형식)·필수 항목 목록·PDF/이미지 첨부 읽기 | A 추출·필수 항목 |
| `Quotation_KEKOREA/app_postprocess.py` | 원본 `app.py`의 추출 후처리 함수(35~323행) 발췌 | A |
| `Quotation_KEKOREA/agent/trade_documents.py`·`pricing.py`·`product_matching.py`·`promotions.py`·`samples.py`·`counterparties.py` | 검증·계산(Decimal)·가격 출처·상품 매칭·프로모션·샘플 행·거래처 정보 | B 계산·가격·매칭 |
| `Quotation_KEKOREA/agent/renderers.py`·`pi_pdf.py`·`branding.py`·`seal_storage.py` | 검토 파일·PDF 출력(외부 라이브러리 없이 직접 생성)·직인 | C 문서 출력 |
| `Quotation_KEKOREA/agent/ci_import.py`·`packing.py`·`packing_review.py` | 첨부 PI → CI, PL 포장 합계 비교·승인 | D CI·PL |
| `Quotation_KEKOREA/agent/workflow_state.py` | 원본 화면의 문서 작업 상태. 이식 대상 아님(`tests/test_pdf_inputs.py`가 import해서 둠) | — |
| `Quotation_KEKOREA/tests/` | 위 모듈의 원본 테스트 16개(화면·계약서 테스트 제외) | 묶음별 |
| `Quotation_KEKOREA/supabase/` | 카탈로그(제품·매입가·판매가)와 거래처 표 정의 SQL 2개(데이터 없음) | B |
| `PRESERVED_BEHAVIOR.md` | 원본 `AGENTS.md`의 '반드시 보존할 동작'·'보호 테스트 위치' | 모두 |
| `SPEC.md` | 원본 `README.md`의 무역서류 설계·동작 설명 발췌 | 모두 |
| `KNOWN_ERRORS.md` | 원본 `docs/history/README_ERROR.md`(2026-11-03 오류 재현 기록, ERR-01~15) | 모두 |

## 원본과 다른 점

넣지 않은 것: 계약서(`contracts/`, 나중에 이식) · 로그인(`Auth/`) · Streamlit 화면(`app.py`의 화면 코드)과 화면 테스트(AppTest) · 계약서 테스트 · 회사 로고·직인 · 회사 가격 시드(원본 레포에도 없음) · 가격표 만들기 스크립트와 그 테스트 · 배포·환경 설정(`render.yaml`, `.env.example`, `requirements.txt`) · 발표·팀 메모 · 과거 계획 문서.

바꾼 것(그 밖의 줄은 원본 그대로):
- 실명·연락처: `app_postprocess.py`의 회사 기본값 주소·대표자·전화·이메일 → `[COMPANY ADDRESS]`·`[REPRESENTATIVE NAME]`·`[COMPANY PHONE]`·`[COMPANY EMAIL]`. `pi_pdf.py`·`renderers.py`의 서명자 실명 → `[AUTHORIZED SIGNER]`. (`.work/RULES.md` 3절: 실명·연락처 금지) [Past work: aio3]
- 가격: 테스트의 실제 값일 수 있는 매입가 `7920` → `8000`(`tests/test_packing_workflow.py`·`tests/test_ci_pi_import.py`). [Request: 회사 가격 복사 금지]
- 파일 이름: 원본 `AGENTS.md` → `PRESERVED_BEHAVIOR.md`(Codex가 하위 폴더의 `AGENTS.md`를 규칙으로 자동으로 읽기 때문), README·오류 기록은 위 표처럼 발췌·이름 변경.
- 실제 거래처 이름(ECLADO·Dear Glow 등)과 상품명은 원본 그대로 둔다(요청자 결정, 2026-11-10). 이식한 코드에서는 사용자별 설정으로 일반화한다(`docs/plans/kekorea-port.md`). [Request]

## 원본 테스트 돌리기

이 폴더에서 실행한다(앱 환경과 따로 돈다). PyMuPDF는 `attachments.py`와 일부 테스트만 쓴다.

```bash
cd reference/kekorea
uv run --python 3.12 --no-project --with 'pymupdf>=1.24' python -m unittest discover -s Quotation_KEKOREA/tests
```

2026-11-10 결과: 155개 중 152개 통과. 실패 3개(`test_trade_documents.py`의 가격 시드 테스트)는 회사 가격 시드(`private/`)가 없어서 원래 실패한다. 원본 레포에서 같은 16개를 돌린 결과와 같다(사본으로 바꾼 줄이 결과를 바꾸지 않음).

## 이식할 때 볼 것

- 이식 순서와 맡은 사람: `docs/plans/kekorea-port.md`.
- 지킬 동작: `PRESERVED_BEHAVIOR.md`. 옮기지 말아야 할 알려진 오류: `KNOWN_ERRORS.md`(2026-11-03 기록이라 그 뒤 고친 것이 섞여 있다. 각 ERR이 이 사본의 코드에서 재현되는지 이식하는 사람이 확인한다).
- PyMuPDF(AGPL)는 `attachments.py`(PDF 첨부 읽기)만 쓴다. 문서 출력(`renderers.py`·`pi_pdf.py`)은 외부 라이브러리를 쓰지 않는다.
- 원본 import 경로(`Quotation_KEKOREA.agent...`)는 사본에서만 맞는다. 이식한 코드는 `app/` 아래 경로로 바꾸고, 옮긴 함수 위에 원본 경로를 주석으로 남긴다.
