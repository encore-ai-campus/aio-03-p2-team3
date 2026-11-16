# 설정의 Gmail·Google 캘린더 연동 계획

- 목표: `/app/settings`의 `로고·직인` 바로 아래에 `연동하기` 항목을 추가한다. 클릭하면 Gmail과 Google 캘린더 카드를 표시하고, 각 사용자가 앱에 로그인한 본인의 Google 계정을 연결·재연결·해제할 수 있게 한다.
- 관련 요구사항: R-04(외부 API), R-12(정상·오류 검증), R-14(사용자 화면·배포).
- 관련 Issue: [1절 #191](https://github.com/encore-ai-campus/aio-03-p2-team3/issues/191), [2절 #192](https://github.com/encore-ai-campus/aio-03-p2-team3/issues/192), [3절 #193](https://github.com/encore-ai-campus/aio-03-p2-team3/issues/193).
- 조율함: 해당 없음 — 계획만 작성하며 그래프 상태·도구 스키마·노드·엣지는 변경하지 않는다.
- 현재 상태: Gmail은 `app/auth/gmail.py`의 `/api/gmail/connect`, `/disconnect`, `/logout`과 `/api/me.gmail`이 구현돼 있다. `frontend/src/pages/SettingsPage.jsx`에는 연동 메뉴가 없다. Google 캘린더 OAuth·연결 상태 API는 없으며 `app/graph/calendar/`의 포트는 실제 공급자와 연결되지 않았다. Supabase 앱 로그인 성공 자체를 Gmail·캘린더 권한 동의로 보지 않는다.
- 진행 방식: 저장소 `.work/RULES.md` 7절에 따라 이 PR은 계획과 최신 흐름만 변경한다. 아래 구현은 계획 병합 뒤 절마다 별도 작업·PR로 진행한다.

## 1. 연동 화면과 기존 Gmail 연결

- 할 일: `SettingsPage.jsx`의 `로고·직인` 다음에 `연동하기`를 추가하고 같은 디자인의 Gmail·Google 캘린더 카드를 만든다. 회사 설정 조회 실패와 무관하게 연동 메뉴에 접근할 수 있도록 조회/오류 경계를 분리한다. Gmail은 기존 Bearer API로 연결을 시작하고 서버가 반환한 Google 동의 주소로 이동한다. `/app/settings?gmail=…`으로 돌아오면 연동 항목을 자동으로 열고 `/api/me`를 다시 읽어 연결·감시 상태와 결과 안내를 표시한다. 해제·재연결·중복 클릭 방지와 401·서버 설정 누락·동의 취소·범위 누락·다른 계정 거절을 처리한다. 캘린더 카드는 2절 전까지 `준비 중`으로 표시해 연결 성공을 가장하지 않는다. 아래 연동 계약과 실제 컴포넌트/조회 경계를 이 절의 구현 결과에 맞춰 기록해 2절이 재사용하게 한다.
- 완료 기준: 메뉴 순서와 카드 두 개를 브라우저에서 확인한다. Gmail 미연결→동의 이동→콜백→연결 표시→해제, 취소·실패·다른 계정·401·연속 클릭과 새로고침을 가짜 Google/인증·실제 임시 PostgreSQL로 검증한다. 회사 설정 API가 실패해도 연동 메뉴가 열린다. 390px·데스크톱에서 조작 가능하고 기존 설정 입력/저장이 유지된다. frontend lint/test/build, `python3 .work/check.py`, `uv run pytest`를 통과한다.
- 영향받는 상태·도구·노드: 프론트 설정 선택·연동 요청 상태, 기존 `/api/me.gmail.connected`·`watch`; 그래프 상태·도구·노드는 변경 없음.
- 섞지 않을 것: 캘린더 OAuth 구현, 일정 조회/생성 도구, 메일 화면 개편, 실제 Google 동의·운영 설정 변경.
- 선행 작업: 없음(이 계획 PR 병합 뒤 시작).
- 하는 사람: Codex.

### 뒤 절에서 재사용할 연동 계약

- 연동 항목 내부 식별자는 `integrations`다. 기존 Gmail 콜백 URL과 `gmail` 결과 매개변수는 유지하고, 캘린더 콜백 결과는 `calendar`로 구분한다. 매개변수는 안내·항목 선택에만 사용하고 연결 여부는 서버 조회로 판단한다.
- Gmail API·`/api/me.gmail`의 기존 형식은 유지한다. 캘린더는 Bearer 전용 `POST /api/calendar/connect`, `POST /api/calendar/disconnect`와 `/api/me.calendar`를 추가한다. 연결 시작 응답은 `{authorization_url}`이며 상태는 `{connected: boolean}`이다. 브라우저에 Google access/refresh token을 반환하지 않는다.
- 본인 계정은 Supabase에서 검증한 Google 공급자 subject와 OAuth 결과 subject가 같은 계정으로 제한한다. 다른 사용자의 토큰·자료를 자동 병합하지 않는다.
- 캘린더 연결에는 `openid`, `email`, `https://www.googleapis.com/auth/calendar.readonly`만 요청한다. 기존 Gmail 필수 범위에 Calendar 범위를 일괄 추가해 Gmail 사용자에게 캘린더 동의를 강제하지 않는다. 일정 생성 권한은 이 요청의 범위에 포함하지 않는다.
- 캘린더의 연결 완료는 state·PKCE·유효 기간·계정·필수 범위·갱신 토큰을 검증하고 본인 캘린더 목록 조회가 성공한 뒤에만 표시한다. Google 캘린더 토큰/동의와 Gmail 감시 상태를 구분하고, 캘린더만 연결할 때 Gmail Pub/Sub 설정을 필수로 요구하지 않는다.
- 연결 해제는 서비스별 앱 사용 중단과 저장 토큰 삭제를 뜻한다. 같은 Google OAuth 클라이언트의 grant 폐기가 다른 서비스 토큰까지 무효화할 수 있으므로 전체 Google 권한 철회는 별도로 명확하게 안내한다. 기존 Gmail 해제의 revoke 의미는 몰래 바꾸지 않으며, 이 작업으로 다른 서비스가 무효화되면 서버 재검증과 화면에 재연결 필요 상태를 반영한다.

## 2. Google 캘린더 OAuth와 연동 카드 활성화

- 할 일: 1절의 연동 계약과 구현 결과를 읽고 `/api/calendar/*`·콜백·`/api/me.calendar`를 구현한다. 기존 Gmail 토큰을 덮어쓰지 않도록 서비스별 암호화 토큰/동의 범위를 저장하고 필요한 Alembic 마이그레이션을 추가한다. state·PKCE·10분 유효 기간·콜백 1회 소비·같은 Google 계정을 검증하고, 갱신 토큰 누락 시 동의를 한 번만 재요청한다. 캘린더 목록 조회로 연결을 확인하고 만료·취소·권한 부족·API 미활성화·통신 실패는 연결 성공으로 처리하지 않는다. 캘린더 카드를 실제 연결·상태 조회·해제·재연결에 연결한다. 기존 Gmail callback과 legacy 로그인 분기를 유지하고 연결 흐름 간 state 혼동을 거절한다. 계약의 인증/DB/환경 절, `.work/design/api-choice.md`의 Calendar 사용 범위와 README의 콘솔·운영 안내를 실제 구현대로 갱신한다. 새 설정이 필요하면 `.env.example`에는 이름·설명만 적는다.
- 완료 기준: 가짜 Google과 실제 임시 PostgreSQL로 정상 연결·갱신·해제·재연결 및 다른 계정·잘못된/재사용/만료 state·PKCE 오류·부분 동의·갱신 토큰 누락·Google 장애·취소를 검증한다. 사용자 A/B의 토큰·상태가 섞이지 않는다. Gmail만 연결/캘린더만 연결/둘 다 연결과 한쪽 해제·grant 폐기의 영향을 검증하고, 기존 메일 수집·발송·로그아웃 회귀 검사를 통과한다. 브라우저에서 콜백 복귀·새로고침·오류 복구를 확인하고 frontend lint/test/build, 규칙 검사와 전체 pytest를 통과한다.
- 영향받는 상태·도구·노드: Calendar 암호화 토큰/동의 범위, `/api/me.calendar`, OAuth 대기 세션의 서비스 구분, 프론트 연동 카드 상태. 그래프 상태·도구 스키마·일정 포트는 변경 없음.
- 섞지 않을 것: 일정 생성/수정/삭제, 자연어 일정 추천, 마스터 그래프·CalendarPort 연결, 보조 일정 API, 실제 개인 토큰/일정의 테스트 기록 저장.
- 선행 작업: 1절 병합.
- 하는 사람: Codex.

## 3. Google 콘솔 설정과 Render 실제 연결 확인

- 할 일: 구현 문서에 맞춰 기존 Google Cloud 프로젝트에서 Calendar API와 동의 범위를 설정한다. Gmail과 Calendar의 실제 callback 허용 주소와 Render 환경을 확인한다. 별도 비밀값은 콘솔/Render에서 관리한다. 테스트용 본인 계정과 가상 메일·일정으로 두 서비스의 동의·연결·재접속·해제와 다른 계정 거절을 확인한다. 같은 클라이언트의 권한 철회가 다른 연동에 미치는 영향도 확인해 필요한 재연결 안내를 검증한다.
- 완료 기준: 운영 `/app/settings`의 메뉴 순서, Gmail·Google 캘린더 카드, 본인 계정 연결과 서버 재조회 상태를 확인한다. 새로고침·취소·권한 거절·잘못된 계정 선택 뒤 복구하고 기존 메일 수집/승인 발송이 유지된다. 실제 확인 결과를 개인정보·토큰 없이 기록하며, API 미활성화/검증 제한/배포 미확인 항목은 미완료로 남긴다.
- 영향받는 상태·도구·노드: Google Cloud OAuth/API 설정, Render 배포 상태, 사용자별 Google 동의 상태. 코드의 그래프 상태·도구·노드 변경 없음.
- 섞지 않을 것: 실사용 메일 발송·일정 자동 등록, 추가 유료 서비스·결제 변경, Codex에 비밀값 전달.
- 선행 작업: 1·2절 병합 및 Render 배포 완료(현재 미확인).
- 하는 사람: 사람(콘솔·계정 설정·실제 Google 동의).
