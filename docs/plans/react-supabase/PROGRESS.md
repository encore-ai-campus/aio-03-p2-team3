# 구현·검증 진행 현황

기준: 2026-11-12, 현재 코드와 로컬 확인 결과. 관련 요구사항 R-03·R-07·R-14.

## 어디까지 구현했나

| 단계 | 코드 상태 | 실제 환경 상태 |
|---|---|---|
| 1 | 전환 계약 확정 | 운영 전환 전 |
| 2 | 콘솔 준비 항목 문서화 | 프로젝트·비공개 버킷·Google OAuth는 사용자 준비 확인, 환경변수 미설정 |
| 3~7 | PostgreSQL 테스트/런타임·Supabase Bearer·React 로그인·Gmail 연결 API | 실제 Supabase 로그인·Gmail 연결 미검증 |
| 8~10 | 첨부·회사 이미지·승인 PDF/XLSX의 Storage 저장·backfill·소유권/해시 확인 | 운영 파일 이전 미실행 |
| 11 | `/app/settings`의 회사·거래처·판매/구매 단가·통화별 계좌·로고/직인 연결 | 가짜 인증·Storage와 임시 PostgreSQL로 확인 |
| 12~21 | 문서 작성·문서함·현황·첨부 화면·메일·실행 기록·같은 출처 배포 | 남음 |
| 22 | 실행 도구·계획 일부 준비 | 실제 데이터 이전·운영 전환 미실행, 사람이 확인할 단계 |

최신 팀 main의 `c6b1600`까지 합쳤으며 사용자별 OpenAI 키·개인 PC 실행기 코드는 유지했다. 실제 DB·Render·키·Google 콘솔은 변경하지 않았다. SQLite 원본과 기존 바이너리 열도 삭제하지 않았다.

## 11절 구현

- 회사·계좌·단가·PNG 이미지는 기존 `/api/trade/settings` API를 재사용한다.
- 거래처는 기존 `counterparties` 표에 `PUT /api/trade/settings/counterparties`만 추가했다. 회사명 정규화 키를 서버에서 만들고 본인 행만 갱신한다. 별칭은 20개까지이며 서버 소유권 필드는 입력으로 받지 않는다.
- 단가의 판매/매입 역할·통화·거래처 범위를 보존한다. 수량/금액을 브라우저에서 확정 계산하지 않는다.
- 저장 실패는 입력을 유지하고 성공 응답을 받은 뒤에만 저장 안내를 표시한다. 다른 레코드/파일을 선택하면 이전 저장 안내를 지운다.
- 회사 이미지는 Bearer 다운로드로 미리 보고 조회 취소·객체 URL 정리를 한다. 새 이미지/설정이 기존 검토·발급 파일을 바꾸지 않는다.
- React/JavaScript/Vite와 기본 폼/CSS를 사용했다. 새 런타임 패키지·폼 라이브러리·상태관리 도구는 추가하지 않았다.

## 이번 확인 결과

사용자의 요청에 따라 11절 구현 후 필요한 확인만 묶어 진행했다. 전체 테스트를 반복하지 않았다.

- `TEST_DATABASE_URL= OPENAI_API_KEY= LANGSMITH_TRACING=false uv run pytest -q tests/test_react_settings.py tests/test_trade_branding_storage.py::test_branding_upload_keeps_bytes_only_in_storage_and_metadata_in_db`: **4 passed, 12.03초**.
- Chromium + 실제 FastAPI/임시 PostgreSQL/가짜 Storage: 회사 저장·실패 입력 보존·재접속, 통화별 계좌, 거래처, 판매/구매 단가 분리, 잘못된 PNG 거부·직인 저장·인증 미리보기, 모바일 너비·키보드·사용자 전환 확인.
- `npm run lint`·`npm run build`: 통과. `python3 .work/check.py`: 경고 0개로 통과.
- 실제 Supabase·Google·OpenAI는 호출하지 않았다. 실제 운영 연결 성공을 뜻하지 않는다.

## 남은 검증

이전 전체 검사에서 통합 오류가 있었고 수정 후 전체 검사를 다시 돌리지 않았다. 최근 별도 검사에서는 개인 PC 실행기 종단 간 시험 1개가 Gmail 후보 완료를 기다리다 시간 초과했다. 실제 사용자 PC의 장애를 확인한 것은 아니다. 이 문제와 CI 전체 통과는 미해결이며 이번 설정 화면 4개 검사 통과와 구분한다.

환경변수 설정 후 실제 Supabase 로그인·비공개 버킷·OAuth 연결 확인이 필요하다. 값은 저장소/채팅에 넣지 않는다. 브라우저에는 `VITE_SUPABASE_URL`·`VITE_SUPABASE_PUBLISHABLE_KEY`, 서버에는 `DATABASE_URL`·`SUPABASE_URL`·`SUPABASE_SECRET_KEY`·`SUPABASE_STORAGE_BUCKET` 및 기존 Google/암호화 설정을 사용한다.

## 다음 작업

Codex: PLAN 12절(PI 작성·검토·승인·다운로드 화면, Issue #140). `REQUESTS.md`의 12번 요청문을 사용한다. 실제 데이터 이전은 21절 배포 검증과 사람의 22절 확인 뒤 진행한다.
