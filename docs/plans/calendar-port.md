# calendar-port 계획

- 목표: 설정 화면의 Calendar OAuth로 저장한 토큰으로 실제 Google Calendar의 바쁜 시간을 읽고 일정을 등록한다. 업무 도우미 대화에서 일정 조회·등록을 쓸 수 있다.
- 관련 Issue: 이 계획의 세 하위 작업 Issue에서 관리한다.
- 관련 요구사항: R-02·R-04·R-11.
- 조율함: 해당 없음. 이 PR은 계획을 기록한다. 3절이 도구 등록부(공통 부분)를 고치므로 구현 전에 관련 팀원과 조율한다.

Calendar OAuth 연결·토큰 저장·상태 조회는 이미 있다(`calendar_tokens`, `app/auth/calendar.py`). 그래프 쪽 계약도 정해져 있다 — `CalendarPort`(`app/graph/calendar/ports.py`), `CalendarInput`·`BusySnapshot`(`app/graph/calendar/schemas.py`), 노드 흐름(`app/graph/calendar/nodes.py`). 없는 것은 이 계약을 만족하는 Google 구현뿐이며, `app/main.py`의 `agent_runtime`이 `calendar=`를 주입하지 않아 기본 구현(`UnavailableCalendar`)이 쓰인다. 구현은 Gmail 연동과 같은 포맷을 따른다 — 호출기(`app/clients/`), 어댑터(`app/graph/<도메인>/adapters.py`, SQL과 Google 호출을 어댑터가 소유), 조립은 `make_workflow` 주입. 계약을 새로 정하지 않으므로 하위 작업 사이에 맞출 새 파일은 없다.

## 1. Calendar API 호출기 확장

- 할 일: `CalendarClient`(`app/clients/calendar.py`)에 세 호출을 더한다. freebusy 조회(지정 캘린더·시간 범위의 busy 구간, 캘린더별 `errors` 포함), 일정 등록(`events.insert` — 제목·시작·끝·시간대·참석자), 등록 확인(`events.get`). 오류 분류는 `check_calendars`와 같은 체계를 쓴다(401 `TokenExpired`, 403은 서비스 비활성·쿼터·권한 구분, 통신 오류 `GoogleUnavailable`). 응답은 필요한 최소 필드만 파싱한다.
- 완료 기준: 모의 HTTP로 정상·401·403 세 종류·5xx·불완전한 응답을 구분하는 단위 테스트가 통과한다. 기존 `check_calendars`·Calendar OAuth 회귀가 통과한다. 실제 Google 호출은 하지 않는다.
- 영향받는 상태·도구·노드: 없음(`app/clients/calendar.py`와 테스트만).
- 섞지 않을 것: 어댑터·그래프·`app/main.py` 변경, 캘린더 목록 조회, 일정 수정·삭제 호출.
- 선행 작업: 없음.
- 하는 사람: Codex.

## 2. ExistingCalendar 어댑터와 영수증 저장

- 할 일: `app/graph/calendar/adapters.py`(신규)에 `CalendarPort` 구현을 만든다. `CalendarToken` 만료 갱신은 `app/auth/calendar.py`의 `calendar_status` 갱신 로직을 헬퍼로 빼서 어댑터와 상태 조회가 같은 코드를 쓰게 한다(Gmail의 `get_access_token`은 건드리지 않는다). `read_busy`는 1절 호출기로 `BusySnapshot`을 만들되 요청한 캘린더 전부를 결과에 포함하고(빈 캘린더도), 캘린더별 조회 오류는 실패 처리한다 — 노드의 완전성 검사를 통과해야 한다. `create`·`lookup`은 action_id PK 영수증 표(`calendar_event_receipts`: user_id, event_id, content_hash)로 멱등을 지킨다. `user_lock` 직렬화 뒤 등록하고 영수증을 저장하며, 같은 action·같은 hash 재실행은 저장 영수증을 돌려주고 다른 hash는 `idempotency_conflict`, 타임아웃·5xx는 재시도 없이 `unknown`이다(Gmail 발송의 `failed_unknown` 계약과 같다). 마이그레이션은 `20261116_calendar_oauth`와 같은 스타일(RLS 포함)이다. `app/main.py`의 `agent_runtime`이 `make_workflow`에 어댑터를 주입해 미연결 기본 구현을 실제 구현으로 바꾼다.
- 완료 기준: 임시 PostgreSQL·가짜 Google 어댑터 테스트가 통과한다 — 조회 완전성(빈 캘린더 포함, 오류 캘린더 실패), 등록 멱등(재실행 같은 영수증, 다른 hash 거부), `unknown` 뒤 `lookup` 복구, 토큰 만료 갱신, 미연결 `calendar_not_connected`. 기존 `FakeCalendar` 노드 테스트와 전체 `uv run pytest`가 통과한다.
- 영향받는 상태·도구·노드: `app/main.py` `agent_runtime` 주입, `calendar_tokens` 갱신 경로, 신규 `calendar_event_receipts` 표. `CalendarPort` 계약과 `nodes.py`는 바꾸지 않는다.
- 섞지 않을 것: `nodes.py` 로직 수정(과거 슬롯 제외 등 별개 수정), `master/tools.py`·프롬프트(3절), 캘린더 목록 조회 화면·API.
- 선행 작업: 1절 병합.
- 하는 사람: Codex.

## 3. 업무 도우미 일정 도구 노출

- 할 일: `AGENT_TOOLS`(`app/graph/master/tools.py`)에 일정 조회(`find_slots`)·일정 등록(`create`) 도구를 추가하고 `wiring.py`의 `choose_tool` 안내에서 "일정 조회/등록은 아직 지원하지 않는다" 문구를 지운다. `PLAN_PROMPT`는 이미 calendar 작업을 안내하므로 그대로 둔다. 누락 조건 질문·후보 선택·등록 승인은 기존 질문/interrupt·채팅 UI를 재사용한다. 도구 입출력과 결과 형식은 계약 17.4절에 기록한다.
- 완료 기준: 가짜 모델·가짜 Google으로 대화 API 테스트가 "다음 주 화요일 2시간 회의 가능한 시간 찾아줘" → 후보 선택 → 승인 → 등록 receipt까지 완주한다. 미연결 사용자에게는 캘린더 연결 안내가 간다. 실제 화면 확인은 요청자가 브라우저에서 한다.
- 영향받는 상태·도구·노드: `AGENT_TOOLS`(공통 부분 — 구현 요청에 `조율함: <팀원>`을 적는다), `choose_tool` 프롬프트, 계약 17.4절.
- 섞지 않을 것: React 화면 변경, 캘린더 목록 조회 도구, 메일 내용을 읽어 일정을 자동으로 만드는 연동.
- 선행 작업: 2절 병합.
- 하는 사람: Codex.
