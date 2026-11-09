# PROJECT_CONTEXT — 최신 흐름

이 레포에서 작업하는 팀원과 AI(ChatGPT·Codex·Claude)가 같은 배경과 현재 상태를 알고 시작하기 위한 문서다. 모든 작업 전에 읽는다. [Request · Past work: aio3]
고치는 방법: 작업을 끝낼 때 **바꾼 영역의 절만** 같은 PR에서 고치고, 그 절의 '마지막 갱신' 날짜도 고친다. 다른 절과 이 머리말은 고치지 않는다(모든 PR이 같은 줄을 고치면 매번 충돌한다). 규칙은 `.work/RULES.md` 5절·6절. [Request · Claude proposal]
남은 작업과 맡은 사람은 이 문서가 아니라 GitHub Issue와 Assignees로 관리한다. [Past work: aio3]
읽음 확인 코드: CONTEXT-W6JO

## 1. 과제 개요
마지막 갱신: 2026-11-05 · 바뀌는 때: 과제 안내가 바뀔 때만

- 과제: 단위 프로젝트 2 (팀 3) 「복합 API 연계 일정 조정 에이전트」. 주제는 확장할 수 있다(식단, 자격증, 정보 탐색 등). 공통 기술 요건은 같다.
- 목표: LangGraph로 다중 도구 선택과 순환형 워크플로우, 자가 성찰·피드백 루프를 만들고, 실제 API 데이터로 시나리오를 시험하고, 서비스를 배포한다.
- 필수 산출물: 에이전트 아키텍처 설계서, 에이전트 시험 결과 보고서. 제출물은 이 둘과 코드 저장소·README, 배포 주소, 발표 PPT다.
- 출처: 노션 '단위 프로젝트 2 안내'(2026-11-05 조회), 요약은 `.work/design/initial-setup.md` 3절.

### 일정
| 날짜 | 할 일 |
|---|---|
| 11/9(월) | 대표 입력·출력과 최소 범위 정하기 |
| 11/13(금) | 설계 초안 |
| 11/18(수) | 핵심 구현·시험·배포 정리 |
| 11/19(목) 오전 | 배포 주소 공유, 다른 팀과 상호 체험 |
| 11/19(목) 15:00 | 최종 제출, 발표(20분 + 질의 5분) |

### 최소 구현 범위 (과제 기준)
1. 사용자 요청의 조건과 누락을 확인한다.
2. 여러 도구 가운데 고르고 호출한 뒤 다음 노드를 정한다.
3. 단기 기억(Session)·장기 기억, 컨텍스트 관리와 요약을 둔다.
4. 오류를 감지하고 고친 뒤 다시 실행하고 검증하는 순환을 둔다.
5. 실제 API로 정상·오류 시나리오를 시험한다.
6. 성찰 전후를 같은 기준으로 잰다.
7. 배포한다(Render 지원). 비밀값은 서버 환경에 두고 다른 팀이 체험할 수 있게 한다.

### 상태 설계 요구 (과제 기준)
- 그래프 상태, 단기 기억, 장기 기억, 컨텍스트, 요약을 설계한다.
- 상태 필드, 기억 연동, 컨텍스트 관리, 오류와 종료 조건을 표로 적는다(설계서에 넣는다).

### 시험 지표 (과제 기준, 성찰 전후 비교)
태스크 완료율, 도구 선택 정확도, 응답 일관성 점수, 평균 재시행 횟수.

### 협업 규칙 (과제 기준)
작업 등록(Issue) → 브랜치 → PR과 설명 → 검토·병합. 상태 객체·도구 스키마·그래프는 고치기 전에 관련 팀원과 조율한다. 이 레포의 구체적 규칙은 `AGENTS.md`에서 시작한다.

## 2. 서비스와 대표 입력·출력
마지막 갱신: 2026-11-09

- 주제: 정함(2026-11-09). 사용자의 Gmail에 메일이 오면(푸시 알림) 에이전트가 답장 후보 2~3개를 만들고, 사용자가 하나를 골라 승인해야만 보낸다. 상대방 답장의 거래 내용으로 인보이스 필수 항목을 검토해, 빠지면 재질문 답장 후보를 만들고 다 있으면 견적서를 만든다. 사용자는 여럿이고 각자 자기 Gmail을 등록해 쓴다. 정한 것·확인한 사실·추천 설계는 `.work/design/mvp-plan-handoff.md`, 구현 계획은 `docs/plans/gmail-quote-mvp.md`.
- 대표 입력·출력: 입력은 사용자 Gmail에 온 메일, 출력은 사용자가 승인한 답장과 견적서 PDF(승인 뒤 답장에 첨부). 구체 시나리오는 계획에서 정한다.
- LLM: Google Gemini API `gemini-3.8-flash`(무료 등급, 환경변수 `GEMINI_API_KEY`). 무료 등급은 입력이 Google 제품 개선에 쓰이므로 실제 개인정보를 넣지 않는다. 근거와 설정 경로는 `.work/design/api-choice.md`. 패키지는 `langchain-google-genai`(`pyproject.toml`).
- 외부 API: Gmail API(사용자별 Google OAuth로 메일 읽기·감시 등록·승인 후 발송)와 Cloud Pub/Sub(메일함 변경 푸시 알림)를 추가했다. Google Calendar는 도구 2(구글캘린더 등록)용으로 유지한다. 특일 정보·단기예보·네이버 지역 검색·네이버 길찾기는 MVP에서 제외하고 `.work/design/api-choice.md`의 '일정 도구 추천 후보'로 옮겼다(2026-11-09 결정). API 연동·콘솔 설정은 별도 작업이다.
- 체험자는 테스트용 Google 계정과 가상 메일을 쓴다. 일정 도구 연결 때도 LLM에는 일정 제목 없이 바쁜 시간대만 넘긴다. 근거·키 발급 경로는 `.work/design/api-choice.md`, 요약은 README 'LLM·외부 API와 키 발급', 환경변수는 `docs/CONTRACT.md` 11절·`.env.example`.
- LLM·외부 API를 더하거나 바꾸는 일은 요청자가 정한다(`.work/TASK.md` 이 레포의 규칙).

## 3. 그래프 상태·기억 (공통 부분)
마지막 갱신: 2026-11-09

- 계약 정함(2026-11-09, `docs/CONTRACT.md` 2절·7절). 코드는 아직 없음(`app/graph/state.py`의 `AgentState`, `docs/plans/gmail-quote-mvp.md#2`에서 만듦).
- 상태: 시작 입력(`run_id`·`user_id`·`mode`·`message_id`·`thread_id`·`email`·`reflection_enabled`), 기억(`thread_context`·`long_term`), 판단(`intent`·`selected_tool`·`tool_reason`·`step_status`), 거래(`deal_terms`·`required_fields`·`missing_fields`), 결과(`reply_mode`·`candidates`·`quote_draft`), 성찰(`reflection`·`reflection_history`), 횟수(`call_retries` 통신·형식 재시도, `reflection_retries`·`reflection_retries_by_type` 성찰 재실행 — 따로 셈), `errors`·`needs_review`·`notice`·`end_reason`, 도구 기록 `tools_called`.
- 기억: 단기는 스레드(threadId) 단위 `thread_messages`·`thread_memory`(요약 포함), 장기는 `user_preferences`·`company_profiles`·`price_list_items`·`counterparty_history`(Render Postgres). 현재 메일 조건이 과거 기억보다 앞선다.
- 고치기 전에 관련 팀원과 조율하고, 코드와 계약을 같은 PR에서 고친다(TASK.md 공통 부분 규칙).

## 4. 도구(API 연동) (공통 부분: 도구 스키마)
마지막 갱신: 2026-11-09

- 계약 정함(2026-11-09, `docs/CONTRACT.md` 4절). 코드는 아직 없음. 도구 하나 = `app/tools/<이름>.py` 하나 + `app/tools/registry.py` 한 줄, 결과는 모두 `ToolResult`(성공 여부·값·오류 종류·출처·조회 시점·시도 횟수·소요 시간).
- `draft_replies`(답장 후보 2~3개, Gemini) · `extract_deal_terms`(거래 항목 추출, Gemini) · `check_required_fields`(필수 항목 검토, 코드, 목록은 `get_required_fields()`) · `draft_followup_replies`(재질문 후보, Gemini) · `create_quote`(견적서 초안, 코드) · `send_email`(승인 뒤 같은 스레드로 발송, Gmail. 그래프 밖 승인 경로에서만 부름).
- 오류: 한도 오류(`rate_limit`)는 재시도 없이 기본 답장 틀 후보 + 안내, 통신 실패는 `LIMITS`까지 재시도 뒤 실패 종료.
- 일정(캘린더) 도구 작업 때 AI가 `.work/design/api-choice.md`의 '일정 도구 추천 후보'를 요청자에게 추천한다. Calendar는 도구 2용으로 유지하며, 후보 API는 채택 확인 후 추가한다.

## 5. 그래프 노드·흐름 (공통 부분)
마지막 갱신: 2026-11-09

- 계약 정함(2026-11-09, `docs/CONTRACT.md` 3절). 코드는 아직 없음(`app/graph/build.py`·`routing.py`).
- 흐름: `load_memory` → `analyze_email` → (일반) `draft_replies` / (거래) `extract_deal` → `check_required` → (빠짐) `draft_followup` / (다 있음) `make_quote` → `draft_replies` → (성찰 켬) `reflect` ↺ 재실행 → `save_pending` → 끝. 실패는 `finish_failed`, 처리 안 함은 바로 끝. 승인·발송은 그래프 밖(`app/services/approval.py`).
- 종료: `awaiting_approval`(정상) · `followup_question`(추가 질문) · `ignored` · `failed`. 성찰 재실행 한도를 넘으면 '확인 필요' 표시로 끝냄(대체 경로).

## 6. 시험·평가
마지막 갱신: 2026-11-05

- 아직 없음. 시험 시나리오(정상·오류), 지표 계산 방법, 성찰 전후 실행 결과를 적는다.
- 같은 시나리오를 다시 돌릴 때의 편차보다 큰 차이만 개선으로 본다. [Past work: aio3]

## 7. 배포
마지막 갱신: 2026-11-09

- 아직 없음. 서버는 Render를 쓸 예정이다. 배포 주소, 첫 요청 지연 같은 주의점을 적는다.
- 환경변수는 `docs/CONTRACT.md` 11절을 기준으로 `.env.example`에 이름과 설명만 둔다. 값은 로컬 `.env`와 Render 환경변수에 두고 Codex에는 키를 넣지 않는다.
- LLM·OAuth: `GEMINI_API_KEY`, `GOOGLE_OAUTH_CLIENT_ID`·`GOOGLE_OAUTH_CLIENT_SECRET`·`GOOGLE_OAUTH_REDIRECT_URI`.
- Gmail 푸시: `GMAIL_PUBSUB_TOPIC`, OIDC 확인용 `PUBSUB_PUSH_AUDIENCE`·`PUBSUB_PUSH_SERVICE_ACCOUNT`, 대체 비밀 토큰 방식일 때만 `PUBSUB_PUSH_TOKEN`.
- 앱 설정: `DATABASE_URL`(Postgres 접속 주소, 로컬에서 비우면 SQLite 파일), `TOKEN_ENCRYPTION_KEY`(Google 토큰 암호화 키), `SESSION_SECRET`(세션 쿠키 서명 키), `APP_BASE_URL`(서비스 주소), `REFLECTION_ENABLED_DEFAULT`(성찰 기본값).

## 8. 문서·산출물 위치
마지막 갱신: 2026-11-09

| 무엇 | 위치 | 상태 |
|---|---|---|
| 과제 요구사항 정리(R-ID·D-ID) | `docs/REQUIREMENTS.md` | 있음(2026-11-09) |
| 에이전트 아키텍처 설계서 | `docs/ARCHITECTURE.md` | 아직 없음(11/13 초안) |
| 에이전트 시험 결과 보고서 | `docs/TEST_REPORT.md` | 아직 없음 |
| 시험 실행 기록(실행마다 한 파일) | `docs/test-records/` | 아직 없음 |
| 큰 작업의 계획 파일 | `docs/plans/gmail-quote-mvp.md` (형식: `docs/plans/README.md`) | 있음(Gmail 견적 MVP 구현 계획) |
| 발표 PPT | 미정 | 아직 없음 |

- 위치는 Claude가 정한 처음 값이다. 팀이 바꾸면 이 표와 README를 함께 고친다. [Claude proposal]
- 설계 결정·오류 사례·수정 이유·버전·재실행 결과는 Issue, PR('오류·재실행 기록' 칸), 팀 노션에도 남긴다.

## 9. 레포 세팅·작업 방식
마지막 갱신: 2026-11-09

- 세팅 단계는 `.work/FLOW.md` 순서로 진행한다. 7단계까지 모두 마쳤다. 다음 과제는 템플릿 레포 `doomdiver100T/aio-team-template`([공통] 파일, [과제별] 빈 틀·최소 실행 틀)의 README '이 템플릿으로 새 과제 시작하기'에서 시작한다(Template repository 켜 둠). 작업량 기준 100KB·도구 1회 크기는 기록을 보고 그대로 두었다(`.work/RULES.md` 8절 5번). 세팅 진행기록은 `.work/STATUS.md`.
- [공통] 파일은 두 레포에서 같게 둔다(읽음 확인 코드 줄만 다름). 이 레포의 고유 값(레포 주소 등)은 [공통] 파일에 쓰지 않고 `.work/TASK.md`에서 가리킨다(RULES 2절 4번의 Issue 주소가 그 예).
- 팀원은 ChatGPT(Codex)로 작업을 맡기고, 세팅 단계는 Claude가 한다. 모두 PR로 올린다. Codex는 새 Codex Cloud의 환경 `aio-03-p2-team3`(워크스페이스 공유, 팀원 모두 GitHub 연결 마침)를 쓴다. 작업은 ChatGPT 왼쪽 `…` → Codex → Cloud · Choose environment에서 시작하고, Codex는 `AGENTS.md`를 자동으로 읽으므로 요청 문구에 그 파일을 읽으라고 쓰지 않는다. 요청 문구에 적지 않아도 `AGENTS.md`의 'Codex가 꼭 할 일'대로 검사·테스트·push·PR까지 하고, Issue는 `Issue: #번호`만 적으면 GitHub에서 본문을 읽는다(환경에 `api.github.com` 허용 뒤, 못 읽으면 본문을 붙임)(팀원 절차: 요청 → PR 확인 → 병합), 답에 PR 링크가 없으면 같은 작업에 후속 요청으로 연다. 연결·요청 문구는 `docs/CHATGPT_GUIDE.md`.
- Codex 환경에는 API 키를 넣지 않는다. Codex에서 도는 테스트는 가짜 응답으로 하고, 실제 API 시험은 로컬과 Render에서 한다.
- 병합: 승인 없이 PR을 연 사람을 포함해 누구나 병합한다. `main`에는 Ruleset 'main 필수 검사'(`rules-check`·`tests`·`pr-check` 필수, 승인·strict 없음)가 있어 검사 통과 전에는 병합되지 않는다. Claude는 병합하지 않고, Codex는 팀원이 요청할 때 검사 통과 뒤에만 병합한다. 병합한 브랜치는 지우지 않는다.
- 기능이 둘 이상 섞인 요청과 '작업 분배'·'작업 배분'·'작업 나누기' 요청(세팅 단계 작업 제외, KB 재기·FLOW·STATUS 안 씀)은 먼저 `docs/plans/<작업명>.md`를 PR로 올리고, 그 AI가 하위 작업마다 Issue(`<작업명>#N <절 제목>`)를 만든다(못 만들면 요청자가 만듦). 절마다 '선행 작업'·'하는 사람(Codex/사람/Claude)'을 적어 선행 작업이 없는 절은 동시에 하고, 맡는 사람은 Issue Assignees에 자신을 넣고 하위 작업마다 새 작업으로 한다(2026-11-09, `.work/RULES.md` 7절, 형식 `docs/plans/README.md`).
- PR '설명' 칸에는 '작동 방식(발표용)'(구현 방식 2~4문장)도 적고 마지막 답에서 요청자에게 따로 짚어 안내하며(Codex·Claude 모두), 계획·설계서·시험 보고서·PR은 요구사항을 `docs/REQUIREMENTS.md`의 R-ID로 가리킨다(2026-11-09, `.work/TASK.md` 이 레포의 규칙).
- 작업 완료 답변에는 별도 요청이 없어도 다음 작업 1~3개의 담당·시작 조건·계획 절·Issue를 안내하고, Codex 하위 작업은 새 작업용 요청문을 함께 준다. 완료 여부를 확인하지 못했으면 `미확인`으로 표시한다(2026-11-09, `AGENTS.md` 5번·`.work/RULES.md` 5절 8번).
- 담당: 미리 정하지 않는다. 누구나 어느 부분이든 맡는다. 프로젝트를 마친 뒤 팀원별 PR 내역을 바탕으로 맡은 바를 정리해 README에 적는다. [Request]
- 실행 환경: Python 3.12, uv. 설치 `uv sync`, 테스트 `uv run pytest`, 패키지 추가 `uv add <패키지>==<버전>`. 자세한 것은 README '실행 방법'. 서버 실행 명령은 코드 구조가 정해지면 더한다.
- 규칙 검사: `python3 .work/check.py`. PR 전에 통과시킨다(테스트는 따로 `uv run pytest`).
- CI: `.github/workflows/rules-check.yml`. PR과 `main` 변경마다 `rules-check`(규칙 검사, 파일 지도에 없는 파일도 오류)와 `tests`(`uv sync --locked` 뒤 `uv run pytest`)가 따로 돈다. `uv.lock`이 `pyproject.toml`과 어긋나면 `tests`가 실패한다. PR에서는(본문을 고쳐도) `pr-check`도 돌아 PR 본문 '읽은 파일' 칸의 읽음 확인 코드(RULES.md·TASK.md·이 문서)와 '최신 흐름 갱신' 칸(이 문서를 안 고쳤으면 `해당 없음 — 이유`)을 본다.
