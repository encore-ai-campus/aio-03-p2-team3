# Calendar OAuth·설정 연동 검증 (#192)

- 대상: `docs/plans/settings-google-integrations.md` 2절, R-04·R-12·R-14.
- 기준: main `8ad74d9`(선행 1절 PR #196 병합).
- 환경: Linux·Python 3.12, 실제 임시 PostgreSQL/pgvector, 가짜 Google/JWKS, 실제 Chromium 155·React/FastAPI. 실제 공급자·개인 계정·메일·일정은 사용하지 않았다.
- 범위: 인증·서비스별 암호화 토큰·카드·문서. 그래프/도구/노드/CalendarPort·일정 등록 변경 없음.

## 확인한 흐름

| 영역 | 검사·결과 |
|---|---|
| 연결·갱신·해제·재연결 | Calendar만 연결(Pub/Sub 설정 없음), 암호화 저장, 만료 갱신, Calendar 토큰만 삭제, 재연결 성공 |
| OAuth | 다른 계정·부분 동의·취소·만료 access token 거부, 갱신 토큰 누락 시 동의 1회 재요청 후 성공/실패 종료 |
| state·PKCE | state 변조·10분 만료·소비된 쿠키 복원/재사용·Gmail/Calendar 흐름 혼동 거부. 실제 Google Flow의 S256 challenge·읽기 전용 범위와 저장 verifier 전달, 공급자의 verifier 불일치 거부 확인 |
| 소유자/서비스 격리 | A/B 토큰·상태 분리, Calendar→Gmail 동시 연결, Calendar 해제 시 Gmail 토큰 암호문/범위 그대로 보존. Calendar 새 표 RLS 확인 |
| 철회·장애 | Gmail 기존 revoke 뒤 공유 grant 무효화 응답을 Calendar 미연결로 반영. API 비활성화/통신 장애는 Calendar 토큰을 보존하고 해당 카드만 미확인, 401/권한 부족은 토큰 삭제. API 응답 원문을 오류에 복사하지 않음 |
| 처리 중 해제 | 공급자 확인 도중 해제하면 늦은 callback이 토큰을 다시 저장하지 못함 |
| 기존 회귀 | 기존 로그인·Gmail 감시/수집·승인 발송·로그아웃·문서/PC 실행 등 전체 pytest 대상 유지 |
| 브라우저 | 회사 설정 API 장애에도 연동 카드 접근, 1440px/390px·가로 넘침 없음, 연속 클릭 방지, 콜백 결과 소비·새로고침, Calendar 단독/동시 연결·해제·취소·API 오류 복구·Gmail 상태 보존·위조 성공 쿼리 거부 |

구현 검사 위치는 `tests/test_calendar_connect.py`(29개), `tests/test_react_settings.py::test_gmail_settings_browser_callbacks_failures_and_mobile`, 기존 `tests/test_gmail_connect.py`와 전체 회귀 검사다.

## 실행 결과

- 전체 `uv run pytest`: **1067 passed, 2 skipped**, 379.31초. 두 skipped는 Windows 전용 검사다. 실제 임시 PostgreSQL을 사용했다.
- 실행 시 `PATH`의 선두는 작업 폴더의 Debian LibreOffice wrapper, `PLAYWRIGHT_BROWSERS_PATH`는 작업 폴더의 설치 Chromium 연결 경로로 지정했다. 서버/검사의 로직·timeout은 유지했다.

- `python3 .work/check.py`: 통과, 경고 0개.
- frontend `npm run lint`·`npm test`(11개)·`npm run build`·`npm run check:env`: 통과.
- Calendar 검사 29개·가짜 공급자 브라우저 흐름: 통과.

## 실패 원인과 재실행

첫 전체 실행은 기존 환경의 LibreOffice XLSX 변환에서 **1 failed·1059 passed·2 skipped**였다. 같은 기존 변환 검사를 별도로 실행해 재현했다. 작업 폴더에 Debian LibreOffice 25.2.3·필요 라이브러리를 풀고 해당 설치의 설정/라이브러리 경로를 지정해 DOCX/XLSX/TXT/이미지 변환 검사 4개를 통과했다. 앱 렌더러·기존 변환 검사는 수정하지 않았다. 전체 재실행도 이 변환기를 사용한다. 브라우저는 설치된 Chromium 실행 파일을 사용했다.

npm 기본 캐시 경로 쓰기 오류는 작업 폴더 캐시로 `npm ci`를 재실행해 해결했다. 고정 패키지·lock은 변경하지 않았다. 내려받은 변환기·캐시·임시 로그/스크린샷은 PR에 포함하지 않는다.

## 실제 운영 확인

Google Calendar API/Data Access 활성화, 게시/검증 제한, 실제 본인 Google 동의, Render 배포/DB migration, 실제 두 서비스의 grant 철회 영향·기존 메일 수집/승인 발송은 **미확인**이다. 사람이 계획 3절 #193에서 확인한다. 자동/가짜 공급자 검사 통과를 운영 성공으로 간주하지 않는다.

## 최신 main 충돌 해결 후 재검증

main `ab01eda`의 로컬 Gmail 저장소 주입·문서함/지식 문서 변경과 Calendar 초기화를 함께 유지했다. `.env.example`·`app/main.py`·`docs/PROJECT_CONTEXT.md` 충돌을 양쪽 변경대로 합쳤다. 전체 pytest **1082 passed·2 skipped**(420.73초), frontend lint/test(11개)/build, 규칙 검사 경고 0개. 그래프·도구·노드 변경 없음.
