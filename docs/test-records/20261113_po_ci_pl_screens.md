# PO·CI·PL 화면 로컬 구현·검증 기록

- 시작 기준: 2026-11-13, main `0cafd0d`. PR 준비 기준은 2026-11-16의 main `f046d24`다.
- 작업 폴더: `C:\encore\aio-03-p2-team3-screens`. 기존 작업 폴더와 설계 전용 작업 폴더는 보존한다.
- 관련: [PLAN 13~15절](../plans/react-supabase/PLAN.md#13), R-03·R-11·R-12·R-14.
- 판정: **로컬 구현과 주요 가상 데이터 발급 흐름 확인, 일부 오류/모바일·운영 검증 남음**. 13~15절의 미확인 항목은 완료로 표시하지 않는다.

## 구현 범위

| 구역 | 실제 연결 |
|---|---|
| 진입 | 기존 문서작성 카드의 PO·CI·PL 링크, 각 새 작성/ID 재개 경로 |
| PO | 공급처 → 구매자(우리 회사) → 품목/매입 단가 → 거래 조건 → 저장/전체 확인 → 최종 검토·승인/취소/수정·다운로드 |
| CI | PI 없는 원문 추출·직접 작성과 본인 PI 문서 불러오기, PI별 최신 버전 목록/페이지·정확한 버전 재확인, PI 남은 작업 경고/별도 보완 탭, 승인 전 선적 정보 준비, 정확한 PI 승인 후 명시적 서버 생성/추출, 검토/발급 |
| PL | 품목별 포장과 별도 packages 편집, 원본/계산 합계·변경·차이·PCS/KG 표시, 별도 합계 승인/취소 후 새 revision으로 최종 검토/발급 |

이후 사용자 결정에 따라 PI 문서번호 중복 확인, PI별 최신본만 선택, PI 없는 CI 직접 작성·원문 추출을 추가했다. 기존 가격 계산·문서 승인 기준·발급 렌더러·DB 스키마·메일 그래프는 변경하지 않았다. 공통 입력/검토 표시에는 문서 종류와 CI 원문 보존에 필요한 prop만 추가했다. 새 패키지·범용 폼/상태 엔진·브라우저 금액 계산·자동 저장은 없다.

## 실행 환경과 자동 확인

실제 임시 PostgreSQL·가상 회사/상품/사용자·가짜 AI/Storage를 사용했다. 운영 DB·실제 키·실제 외부 API·Render 설정을 사용하거나 변경하지 않았다. Linux 전체 검사는 Python 3.12.16 컨테이너에 추적/비무시 소스만 복사해 실행했으며 `.env`·개발 가상환경·node_modules는 복사하지 않았다. 컨테이너의 DB는 임시 영역이다.

| 명령/확인 | 결과 |
|---|---|
| `frontend`: `npm test` | 10 passed. 기존 PI 4개와 PO/CI/PL 각 2개 |
| `npm run lint`·`npm run build` | 통과. 101 modules, 새 의존성 없음 |
| React 서버 렌더 확인(Vite SSR·react-dom/server) | PI 기본 지급/계좌 표시 유지, PO 역할, CI 지급/은행 숨김·원본/선적 표시, PL 두 포장 행/단위·가격 열 없음·치수/배송 표시, CI 보완 폼 입력값 표시 확인. 브라우저 조작/레이아웃 확인과 구분 |
| Windows 초기 `tests/test_ci_source_pis.py tests/test_trade_domain_api.py -q` | 15 passed. 이어 검증 순서 회귀 추가 후 source-pis 모듈 3 passed |
| Linux 전체 `uv sync --locked` → `uv run pytest` 첫 실행 | 924 passed·2 failed·2 skipped, 518.45초. 아래 키 검사 준비값 문제 2건 |
| 키 검사 CI 사례 2개 준비값 수정 후 Windows 표적 재실행 | 2 passed, 19.40초 |
| Linux 전체 최종 재실행 | **926 passed·2 skipped, 361.32초**, 종료 코드 0. PostgreSQL 사용. skip은 Windows 전용 2건 |
| 규칙 검사·`git diff --check` | `uv run python -X utf8 .work/check.py`: 통과·경고 0개. 공백 검사 통과. Windows의 python3 별칭 대신 같은 검사 스크립트를 uv Python으로 실행 |

첫 전체 검사에서 `test_local_openai.py::test_four_document_http_paths_use_local_owner_key_only[ci]`와 `test_openai_keys.py::test_document_ai_requires_owner_key_and_never_uses_server_key[ci]`가 존재하지 않는 PI로 AI 호출을 기대해 실패했다. 승인받은 선행 검증 때문에 이제 올바르게 `SOURCE_PI_NOT_FOUND`가 먼저 반환된다. 각 검사 사용자에게 본인 승인 PI 테스트 자료를 준비해 기존 SDK 키/본인 범위/키 누락 검증을 유지했다. 응답 기대를 완화하거나 실제 승인 규칙을 변경하지 않았다.

## 요구사항별 근거와 남은 확인

아래 과거 버전 선택·55버전 페이지 검증 기록은 당시 동작의 이력이다. 이후 사용자 결정으로 새 CI 선택 목록은 PI별 최신 버전만 표시하고, 페이지 검사는 서로 다른 PI 55건을 사용한다. 이미 연결된 과거 원본의 재조회와 거래가격 보존은 유지한다.

| 설계 요구 | 자동/코드 근거 | 브라우저에서 남은 확인 |
|---|---|---|
| PO 공급처/구매자·매입 가격·PI 은행 분리 | `po-input.test.js`, `test_trade_domain_api.py`의 PO 가격/역할·출력 검사 | 직접/추출 시작부터 발급까지, 누락 질문·공급처/통화 변경·할인/무상 입력 |
| CI 세 상태 목록·정확한 버전·중복 제거 | `test_ci_source_pis.py`: 미완성/미승인/승인·동일 버전 중복 approved 제안·정확한 재확인 | 각 상태를 실제 선택해 경고/보완 링크 확인 |
| CI 승인 전 준비와 명시적 생성 구분 | `ci-input.test.js`: checked·approved·정확한 ID/revision gate, 선적 사전 입력/추출 병합. CIPage는 미승인 시 생성/추출 요청 차단 | PI 별도 탭 보완 중 원문/선적 입력 유지, 같은 버전 승인 재확인, revision 변경 후 명시적 재선택, 재확인만으로 자동 생성 없음 |
| CI 과거 승인 버전·가격/수량/FOC 고정 | source-pis 검사에서 v1 승인→v2 가격 수정→목록 v1 선택→CI 발급 및 PDF/XLSX SHA-256 대조. 기존 도메인 검사에서 현재 단가표 변경·FOC/0원 샘플 보존 | 요약/전체 확인·발급 파일의 화면상 원본 버전 대조 |
| 50개 초과·오류·타인 PI | source-pis 검사: 55버전의 50+5 페이지, 과거 버전 정확한 재확인, cursor/조회 오류 422, 타인 목록 제외·상세/생성 404, 미승인 생성 409·AI 0회 | 더 보기/빈 목록/조회 실패/지연/재시도·사용자 전환, 생성 실패 시 입력 보존 |
| 저장 CI 원본 교체 거부·이전 CI 연결 보완 | 기존 도메인 API의 원본 교체 409·legacy CI 조회/보완 검사. CIPage의 고정 원본/새 CI 안내 | 기존 ID 재개·legacy 원본 선택/보완·새 CI 이동 |
| CI 결제/은행 제외·FOC | `test_trade_ci_import.py::test_actual_ci_files_preserve_foc_sample_and_totals_without_pi_bank_or_payment_values`의 PDF/XLSX/HTML 검사, 도메인 API FOC 검사, 서버 렌더의 지급/은행 숨김 확인 | 화면에서 PDF/XLSX 다운로드·검토 표시와 내용 대조 |
| PL 두 포장 배열·원본 표기·단위 분리 | `pl-input.test.js`, 도메인 API·포장 검사. 서버 렌더에서 두 배열·PCS/KG·치수/배송 표시 확인 | 직접/추출 입력·별도 packages·컨테이너 없음/2 x 40FT·누락 질문 |
| PL 합계 승인/취소와 최종 승인 분리 | helper는 원본 차이만으로 차단하지 않으며 invalid/미저장/오래된 버전 차단. 도메인 API는 원본 복원·새 revision·수정 후 승인 초기화/잘못된 행 거부 확인 | 합계 승인 뒤 자동 발급 없음, 취소/행 수정/최종 modify 후 합계 재확인, 오류 보완 |
| 승인/취소/수정·동시성·파일 해시 | 기존 도메인 API의 세 문서 승인/취소/수정·이력·중복 승인·타인 파일 차단. 각 다운로드 bytes와 발급 `content_hash` 대조 검사 | ID 새로고침·409 입력 보존·최신본 읽기 안내·빠른 중복 클릭·다운로드 실패 후 재시도 |
| PI 회귀·모바일·접근성 | PI 기본 helper 4개/서버 회귀 및 기본 snapshot 표시 유지. 기존 CSS·label·focus·disabled/alert 사용 | PI 실제 작업 회귀, 세 새 화면의 1440·768·390px·키보드·가로 넘침·토큰 갱신·이동/취소·사용자 초기화 |

## 브라우저 검증 중단

로컬 가짜 인증·AI/Storage와 임시 PostgreSQL의 별도 검증 진입점을 준비했지만, Windows 컴퓨터 사용 도구가 브라우저 현재 주소를 충분히 확신할 수 없다는 정책 오류로 중단했다. 검증용 진입점에서 새 화면 완주를 관찰하지 못했다. 다른 자동화 수단으로 이 제한을 우회하지 않았다. 임시 인증 진입 파일은 저장소에서 제거했고 검증 서버도 종료했다.

다음 검증은 브라우저 도구를 사용할 수 있는 환경에서 위 마지막 열을 실제 화면으로 확인하는 일이다. 자동/API 검사와 SSR은 화면 완료의 대체 근거가 아니다. 실제 Supabase·Google 로그인·사용자 OpenAI 키·운영 이전은 기존 계획 22절의 별도 확인 범위다.

## 브라우저 검증 재개

- 임시 PostgreSQL·가상 인증/AI/Storage를 쓰는 별도 로컬 화면으로 재개했다. PO 원문 추출 후 공급처 주소·지급 조건을 보완하고 매입 단가 3·합계 USD 30을 확인했다. 검토 취소, 수정 후 revision 3 재검토/발급, 두 다운로드 파일의 서버 기록 SHA-256 일치, ID 재개, 409 시 미저장 입력 보존과 최신 revision 4 재조회까지 확인했다.
- CI 첫 진입에서 초기 참조가 null일 때 화면이 비는 오류를 발견해 존재 확인을 추가했다. 재진입 뒤 세 PI 상태 표시, 미승인 작성 준비와 생성/추출 잠금, PI 별도 탭 보완/승인 중 입력 보존, 새 revision의 명시적 재선택 및 자동 생성 없음, 50개 이후 승인 버전 선택을 확인했다.
- PI v1 승인 후 v2가 수정된 사례의 v1로 CI를 작성해 단가 8·유상 10·무상 5·합계 USD 80을 검토하고 발급했다. 화면 실행 오류는 0개였다.
- PL 원문 추출과 주소 보완 뒤 원본/계산 차이, PCS/KG 분리와 원본 `2 x 40FT` 표기를 확인했다. 합계 승인은 revision 3을 만들었고, 별도 최종 검토와 승인으로 PDF/XLSX 발급 상태에 도달했다. 화면 실행 오류는 0개였다.
- 모바일 크기·키보드, 다운로드 실패 재시도, CI/PL의 추가 오류·수정 경로 등 위 표의 나머지 화면 검증은 아직 남아 있다. 현재 검증 서버는 가상 자료 전용이다.

## 최신 결정: CI 단독 작성

- 가상 데이터 브라우저에서 PI 없이 CI를 만들고 거래처 주소 누락 보완, 기존 판매 단가 8 및 합계 USD 80, 최종 검토와 PDF/XLSX 발급 버튼을 확인했다. 운영 데이터나 실제 외부 메일은 사용하지 않았다.
- 독립 API 검사는 판매 단가와 명시적 단가 변경, PI 연결 방식으로의 전환 거부, 타인 조회 거부, 발급 파일 해시와 PDF FOC 표기를 확인한다. 모바일과 단독 화면의 추가 오류 경로는 별도 확인이 필요하다.

## PR 준비 재검증(2026-11-16)

- 최신 main `f046d24`에 원격 PC 프로세스 시험 시간 초과 수정 PR #186을 통합했다. 최초 전체 실행에서 XLSX ZIP 생성 시각 변화로 발급 재시도 검사 1건이 실패했다(976 passed·1 failed·2 skipped). 이전에 승인받아 별도 브랜치에서 검증한 ZIP 메타데이터 시각 고정만 반영했고, 직인 유무별 생성 시각 회귀 검사 2건을 포함했다. 실패 검사와 렌더러 표적 검사는 11 passed다.
- 최종 Linux·임시 PostgreSQL 전체 `uv run pytest`: **979 passed·2 skipped, 417.56초**, 종료 코드 0. Windows 전용 2건만 건너뛰었다. 프론트엔드 `npm test`는 11 passed, lint/build와 규칙 검사는 통과·경고 0개다.
- 사용자가 기존의 PR 보류 지시를 철회하고 커밋·push·PR·검사 후 병합을 요청했다. 화면의 남은 모바일·추가 오류 경로와 실제 계정/운영 연결은 이 자동 검사의 완료 범위에 포함하지 않는다.

## Issue #141 PO 화면 추가 확인(2026-11-16)

- 기준: PR #189가 병합된 `main` `bd76427`. Edge의 반응형 화면과 가상 사용자·AI·Storage·임시 PostgreSQL만 사용했다. 아래 직접 작성 자료는 PO ID 7이며 실제 거래 자료가 아니다.
- 1440·768·390px에서 공급처 작성 단계와 저장 후 전체 확인/최종 검토를 확인했다. 1440px은 데스크톱 사이드바·오른쪽 요약, 768·390px은 좁은 화면 배치와 하단 이동 메뉴가 보였다. 390px 품목 표는 표 내부에서 가로로 이동했고 본문 전체가 가로로 밀리는 모습은 보이지 않았다. 세 크기에서 화면의 `런타임 오류` 표시값은 0이었다. 가로 넘침은 시각 확인이며 DOM 수치 측정은 하지 않았다.
- 키보드 `Tab`으로 공급처 회사명 → 주소 → 추가 정보 펼치기 순서와 최종 검토의 고정 정보 펼치기 → 검토 취소 버튼 포커스를 확인했다. 포커스 테두리가 보였고 `Enter`로 검토 취소가 실행됐다. 취소 뒤 문서는 `검토 가능`으로 남았다.
- 직접 작성에서 주소를 비운 채 저장하자 서버가 `입력 필요` 버전 1을 반환하고 주소 입력 칸으로 안내했다. 임의 상품 `QA Product`/단가 3으로 재저장하자 상품 일치·가격 출처·가격 확인 오류와 보완 버튼이 표시됐으며 발급 가능 상태로 넘어가지 않았다. `Virtual Serum`, 납품 조건 `FOB Busan`, 지급 조건 `Net 30 days`로 고치자 USD 매입 단가 3, 수량 10, 합계 30으로 `검토 가능` 버전 3이 됐다.
- 390px 화면에서 최종 검토를 생성했다. 검토의 `수정`으로 돌아가 할인율 10%·무상 수량 2를 저장하자 버전 4에서 유상 10/무상 2, USD 27로 계산되고 새 검토에 반영됐다. 같은 ID를 새로고침해도 버전 4·USD 27이 유지됐다. 공급처 이름을 바꾼 뒤 직접 단가 확인은 선택되지 않았고, 저장 후 USD 매입 단가표와 일치하는 값 3으로 버전 5가 검토 가능했다.
- 통화를 EUR로 바꾸어 저장하자 검증된 EUR 매입 단가가 없다는 안내와 품목 보완 경로가 표시되고 버전 6은 `입력 필요`·EUR 0으로 남았다. USD로 되돌려 저장하자 버전 7이 `검토 가능`·USD 27로 복구됐다. 화면 코드·가격·승인 규칙을 바꿀 재현 결함은 발견하지 못했다.
- PO의 가짜 AI 추출→누락 보완, 제안 취소/수정/승인, PDF/XLSX 발급 해시, ID 재개와 409 미저장 입력 보존은 위 `브라우저 검증 재개`에서 별도의 가상 문서로 이미 확인했다. 이 추가 확인에서는 실제 계정·운영 연결이나 파일을 다시 발급하지 않았다.
- 이번 브랜치의 `uv run python -X utf8 .work/check.py`는 경고 0개, `git diff --check`는 통과했다. `frontend`의 `npm test`는 11 passed, `npm run lint`와 `npm run build`도 통과했다. 추적·비무시 소스만 복사한 Linux·임시 PostgreSQL의 전체 `uv run pytest`는 **979 passed·2 skipped, 1281.69초**, 종료 코드 0이었다. skip은 Windows 전용 검사 2건이다.
- Windows의 전체 `uv run pytest`는 42%에서 PO 범위 밖의 실패가 나타나 중단했으므로 전체 성공으로 기록하지 않는다. 분리 재실행에서 DB 이전 검사는 임시 SQLite 복사본 삭제 `WinError 32`로 1 failed·6 passed, 정적 파일 검사는 테스트용 심볼릭 링크 권한 `WinError 1314`로 1 failed·2 passed, 로컬 Gmail 실행기 검사는 종료 코드 1과 종료 로그 누락으로 1 failed·30 passed였다. 이 세 Windows 문제는 이번 PO 화면 검증에서 수정하지 않았다.

## Issue #142 CI 오류 경로 추가 확인(2026-11-16)

- 기준: PR #190 병합 커밋 `d124e31`의 새 작업 브랜치. 운영 데이터·계정은 사용하지 않았다.
- 프런트엔드 `npm test`: **11 passed**. CI helper에서 미승인 PI의 서버 생성 차단, 승인된 정확한 ID/revision만 허용, PI 보완·추출 뒤 선적 사전 입력 보존을 확인했다.
- 서버 `uv run pytest tests/test_ci_source_pis.py tests/test_trade_domain_api.py tests/test_trade_renderers.py -q`: **28 passed**. 목록·페이지네이션·정확한 revision·소유권/승인·409 및 발급 렌더링 회귀 검사를 포함한다.
- 전체 `uv run pytest`: **974 passed·5 failed·2 skipped**, Windows에서 1200.28초. 실패 5건은 범위 밖 기존 환경 문제인 `tests/test_db_copy.py` 3건의 SQLite 파일 잠금 `WinError 32`, `tests/test_frontend_serving.py` 1건의 심볼릭 링크 권한, `tests/test_local_gmail.py` 1건의 graceful shutdown 로그 누락이다. 관련 소스는 이번 작업에서 수정하지 않았다.
- `python3 .work/check.py`는 Windows에서 Python Store 별칭 오류로 시작하지 못했다. 동등한 `uv run python -X utf8 .work/check.py`는 통과·경고 0개다. frontend `npm test`는 11 passed다.
- 가상 데이터 브라우저에서 390px CI 원본 선택 화면의 오류 복구를 확인했다. DevTools 네트워크를 Offline으로 설정하자 `/api/trade/ci/source-pis` 요청이 실패했고 화면에 네트워크 오류와 `목록 다시 읽기` 버튼이 나타났다. `Disabled: No throttling`으로 복구한 뒤 버튼을 누르자 목록이 다시 로드되어 `PI-APPROVED`, `PI-READY-UNAPPROVED`, `PI-MISSING`, `PI-HISTORY-55`가 표시됐다. CI 앱 런타임 오류 표시는 계속 0이었다.
- CI 화면을 1440·768·390px로 확인했다. 1440px은 데스크톱 화면, 768px은 사이드바가 숨고 하단 메뉴가 보이는 좁은 화면, 390px은 세로 PI 목록과 선적 입력 화면을 확인했다. 세 크기 모두 화면 전체가 가로로 밀리는 현상은 관찰하지 않았다(정량 DOM 측정은 하지 않음). 390px CI 선적 정보 입력에서 Tab 키로 문서번호 → 선적 참조 → 원산지 입력칸으로 이동하고, 입력한 CI-QA-KB-390 및 SHIP-KB-1 값이 유지됐다.
- 저장된 가상 단독 CI 문서 6(`/app/trade/ci/standalone/6`)을 열어 거래·선적 조건 수정 단계와 기존 문서번호·선적 참조·원산지·납품 조건을 확인했다. 문서에 저장하지 않았다. 문서 7 경로는 `문서를 찾을 수 없습니다`를 표시했으므로 이를 편집/409 증거로 사용하지 않았다.
- 문서 6을 새 탭에서 다시 열어 전체 확인 화면도 확인했다. `Item 1 has no verifiable exact quote from the prompt` 경고 때문에 `최종 검토 만들기`가 비활성화되어 있었다. 이는 테스트 문서의 추출 근거 충돌이므로 이를 해소하지 않은 채 최종 발급·다운로드 실패 경로를 시험하지 않았다.
- 768px에서 PI-MISSING을 선택하고 선적 정보를 입력했다. 화면은 구매자 주소 누락과 PI의 승인하고 파일 발급 완료를 남은 작업으로 안내했고, CI 생성은 비활성 상태였다. 화면의 PI 보완·승인하기 경로와 상태 다시 확인 버튼도 보였다. PI를 보완하거나 승인하지 않았고 서버 CI 생성도 시도하지 않았다.
- 가상 단독 CI 초안 8을 만들어 구매자·품목·선적 정보를 입력했다. 전체 확인에서 유상/무상 수량이 비어 있다는 검증 오류가 표시되고 최종 검토 만들기가 비활성화됐다. 이는 필수값 차단의 정상 동작이었다. 초안은 임시 검증 DB에만 생성됐고 파일 발급은 하지 않았다.
- 가상 단독 CI 초안 8의 전체 확인에서 `최종 검토 만들기`를 눌러 승인 대기 제안을 생성했다. 제안의 `수정`이 거래처 입력 단계로 돌아가는 것을 확인했다. 승인하거나 파일을 발급하지 않았다.
- 두 탭을 같은 버전 2로 연 뒤 한 탭에서 거래처 주소를 `2 Fiction Ave, Seoul`로 수정해 저장하고 버전 3 검토를 만들었다. 이전 버전 2 화면에서 `3 Fiction Ave, Seoul`을 입력해 저장하자 409 충돌 안내 `최신 문서를 다시 확인하세요`가 표시됐다. 최신본 다시 읽기가 현재 입력을 교체할 수 있다는 경고와 입력값 `3 Fiction Ave, Seoul`이 화면에 남은 것도 확인했다. `최신본 다시 읽기`는 누르지 않았다.
- 발급 완료된 별도 가상 단독 CI(`/app/trade/ci/standalone/8`, 문서번호 `CI-QA-STALE-409`)에서 PDF와 XLSX 다운로드를 각각 오프라인으로 요청해 네트워크 오류 안내와 실패한 fetch를 확인했다. 네트워크를 `Disabled: No throttling`으로 복구하고 두 파일을 다시 요청하자 각 요청이 HTTP 200으로 완료됐다. `CI-20261116-001-r3.pdf`와 `CI-20261116-001-r3.xlsx`(3.4 KB)가 브라우저 다운로드 목록에 나타났다.
- 이 화면 경로에서 재현된 제품 결함이 없어 코드 수정은 하지 않았다. 가상 CI는 임시 검증 DB를 사용했으며 이 확인에서는 새 승인·파일 발급을 하지 않고 이미 발급된 파일 다운로드만 재시도했다. 메일은 발송하지 않았다. 테스트 결과와 실제 화면 관찰 범위를 구분한다.


- The first Linux container full run reported 1033 passed, 2 failed, 2 errors, and 2 skipped. Node/npm was missing, so the browser build test could not run. Linux isolated reruns passed: worker process tests 6/6 and the local Gmail shutdown test 1/1. The full Linux suite is left to PR CI with the workflow prerequisites.
- Minimal test fixes: `app/db/copy_data.py` now closes the temporary SQLite migration engine, preventing Windows `WinError 32`. The symlink test skips only on Windows `WinError 1314`. Two browser tests invoke `npm.cmd` through the Windows shell. The Gmail shutdown test expects Windows forced termination semantics while retaining the graceful shutdown assertion on POSIX.
- Windows full `uv run pytest`: 1037 passed, 3 skipped, 1476.57s. LibreOffice, Playwright Chromium, and `npm ci` were installed for the run. The skips were 2 Windows-only worker tests and the unavailable Windows symlink privilege. Frontend `npm test` passed 11, and lint, build, `check:env`, `uv run python -X utf8 .work/check.py` (0 warnings), and `git diff --check` passed. Direct `python3 .work/check.py` hit the Microsoft Store alias.
