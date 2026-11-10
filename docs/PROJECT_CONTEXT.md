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
마지막 갱신: 2026-11-10

- 주제: 정함(2026-11-09). 사용자의 Gmail에 메일이 오면(푸시 알림) 에이전트가 답장 후보 2~3개를 만들고, 사용자가 하나를 골라 승인해야만 보낸다. 상대방 답장의 거래 내용으로 인보이스 필수 항목을 검토해, 빠지면 재질문 답장 후보를 만들고 다 있으면 견적서를 만든다. 사용자는 여럿이고 각자 자기 Gmail을 등록해 쓴다. 정한 것·확인한 사실·추천 설계는 `.work/design/mvp-plan-handoff.md`, 구현 계획은 `docs/plans/gmail-quote-mvp.md`.
- 대표 입력·출력: 입력은 사용자 Gmail에 온 메일, 출력은 사용자가 승인한 답장과 견적서 PDF(승인 뒤 답장에 첨부). 구체 시나리오는 계획에서 정한다.
- LLM: Google Gemini API `gemini-3.8-flash`(무료 등급, 환경변수 `GEMINI_API_KEY`). 무료 등급은 입력이 Google 제품 개선에 쓰이므로 실제 개인정보를 넣지 않는다. 근거와 설정 경로는 `.work/design/api-choice.md`. 패키지는 `langchain-google-genai`(`pyproject.toml`).
- 외부 API: Gmail API(사용자별 Google OAuth로 메일 읽기·감시 등록·승인 후 발송)와 Cloud Pub/Sub(메일함 변경 푸시 알림)를 추가했다. Google Calendar는 도구 2(구글캘린더 등록)용으로 유지한다. 특일 정보·단기예보·네이버 지역 검색·네이버 길찾기는 MVP에서 제외하고 `.work/design/api-choice.md`의 '일정 도구 추천 후보'로 옮겼다(2026-11-09 결정). API 연동·콘솔 설정은 별도 작업이다.
- Google 로그인·감시 등록(계획 6절, 2026-11-10): 받은 메일 화면 'Gmail 연결하기' → `/login`('테스트용 Gmail로 등록하세요') → Google 동의 → 토큰을 Fernet으로 암호화해 저장 → `users.watch`(받은편지함만) 등록 → `/inbox`에 연결된 메일·알림 상태·로그아웃. 크론 없이 로그인·화면 요청(응답 뒤)·알림 수신 때 마지막 갱신이 24시간을 넘었거나 실패했으면 다시 등록하고, 로그아웃하면 멈춘다. 갱신 토큰 만료면 '다시 로그인', 등록 실패면 '다시 시도' 안내를 보인다. 실제 Google 연결 확인은 Google Cloud 설정(5절) 뒤 로컬·Render에서 한다. 이름과 규칙은 `docs/CONTRACT.md` 7·9·10절.
- Gmail 알림 수신(계획 7절, Issue #53, 2026-11-10): `POST /gmail/push`에서 OIDC(대상·발급자·서명·만료·인증된 서비스 계정 이메일)를 확인하고 204 응답 뒤 `BackgroundTasks`로 처리한다. 검증 공개 키는 5분 단위로 캐시하며, OIDC 설정이 없을 때만 `PUBSUB_PUSH_TOKEN` 비교를 쓴다. 인증 실패는 403·서버 로그만, 알림 형식 오류는 400이다. 감시의 마지막 `history_id` 이후 `messagesAdded`를 모든 페이지에서 읽고, 자기 발신·SENT·no-reply·프로모션·소셜·받은편지함 밖 메일은 `ignored`로 남긴다. 텍스트/HTML·중첩 MIME 본문을 계약의 `EmailMessage`로 바꾼다.
- 체험자는 테스트용 Google 계정과 가상 메일을 쓴다. 일정 도구 연결 때도 LLM에는 일정 제목 없이 바쁜 시간대만 넘긴다. 근거·키 발급 경로는 `.work/design/api-choice.md`, 요약은 README 'LLM·외부 API와 키 발급', 환경변수는 `docs/CONTRACT.md` 11절·`.env.example`.
- LLM·외부 API를 더하거나 바꾸는 일은 요청자가 정한다(`.work/TASK.md` 이 레포의 규칙).

## 3. 그래프 상태·기억 (공통 부분)
마지막 갱신: 2026-11-09

- 계약의 `AgentState`·자료 형식·초기값을 `app/graph/state.py`에 구현했다(계획 2절, 2026-11-09). `tools_called`·`reflection_history`·`errors`·`call_retries`는 누적 리듀서다. 통신 재시도와 성찰 재실행은 별도로 유지한다. 기억을 읽고 쓰는 업무 본문은 아직 빈 틀이다.
- 상태: 시작 입력(`run_id`·`user_id`·`mode`·`message_id`·`thread_id`·`email`·`reflection_enabled`), 기억(`thread_context`·`long_term`), 판단(`intent`·`selected_tool`·`tool_reason`·`step_status`), 거래(`deal_terms`·`required_fields`·`missing_fields`), 결과(`reply_mode`·`candidates`·`quote_draft`), 성찰(`reflection`·`reflection_history`), 횟수(`call_retries` 통신·형식 재시도, `reflection_retries`·`reflection_retries_by_type` 성찰 재실행 — 따로 셈), `errors`·`needs_review`·`notice`·`end_reason`, 도구 기록 `tools_called`.
- 기억: 단기는 스레드(threadId) 단위 `thread_messages`·`thread_memory`(요약 포함), 장기는 `user_preferences`·`company_profiles`·`price_list_items`·`counterparty_history`(Render Postgres). 현재 메일 조건이 과거 기억보다 앞선다.
- 고치기 전에 관련 팀원과 조율하고, 코드와 계약을 같은 PR에서 고친다(TASK.md 공통 부분 규칙).

## 4. 도구(API 연동) (공통 부분: 도구 스키마)
마지막 갱신: 2026-11-10

- 계약의 입력 스키마·도구 6개 등록과 `ToolResult`를 구현했다(계획 2절, 2026-11-09). 잘못된 스키마 입력은 `invalid_input` 결과로 돌려준다. `create_quote`·`send_email`은 아직 업무 본문이 빈 틀로, 미구현 결과를 반환하며 실제 API를 부르지 않는다.
- `draft_replies` 구현(계획 8절, 2026-11-10): `call_structured()` 1회로 후보 2~3개(`label`·`body`)를 받는다. 개수가 2~3개가 아니면 형식 오류로 1회 다시 부른다. 제목은 코드가 `Re: <원래 제목>`으로 정하고, 사용자 선호의 `signature`가 있으면 본문 끝에 붙인다. `source`는 `gemini:gemini-3.8-flash`, DB 저장은 `save_pending` 노드가 한다. `quote` 모드는 견적서 요약만 프롬프트에 넣어 두었고 11이 다듬는다.
- 거래 도구 구현(계획 10절, 2026-11-10): `extract_deal_terms`는 Gemini 1회로 거래처명·품목(이름·수량·단위·합의 단가)·납기·선택 항목·근거 조각을 뽑고, 빈 값·0 이하 수량·값 없는 필드의 근거를 코드로 정리한다(`extract_deal_terms.v1`). `check_required_fields`는 `get_required_fields()` 목록 순서대로 빠진 키를 코드로 찾는다(품목 키는 품목마다 검사, 단가는 검사 안 함). `draft_followup_replies`는 Gemini 1회로 후보 2~3개를 받고(개수 오류는 형식 오류 재시도), 제목·서명은 `draft_replies`와 같은 방식으로 코드가 정하며, 모든 후보의 `asks_fields`를 빠진 항목 전부로 채운다(`draft_followup_replies.v1`). 프롬프트 텍스트는 `app/prompts/format.py`를 함께 쓴다.
- 대체 후보 `app/tools/fallback.py`의 `fallback_candidates(email, kind=, asks_fields=, preferences=)`: 한도 오류 때 기본 답장 틀 1개(`needs_review=True`, `notice="rate_limit"`)를 만든다. 후보의 `notice`에는 키만 두고, 화면 문구는 `NOTICE_MESSAGES["rate_limit"]`('한도 초과로 AI 후보를 만들지 못했습니다…')를 쓴다(9가 화면에 표시). 재질문 노드(10)는 `kind="followup"`, `asks_fields`=빠진 항목으로 쓴다.
- `draft_replies`(답장 후보 2~3개, Gemini) · `extract_deal_terms`(거래 항목 추출, Gemini) · `check_required_fields`(필수 항목 검토, 코드, 목록은 `get_required_fields()`) · `draft_followup_replies`(재질문 후보, Gemini) · `create_quote`(견적서 초안, 코드) · `send_email`(승인 뒤 같은 스레드로 발송, Gmail. 그래프 밖 승인 경로에서만 부름).
- `app/llm/client.py`의 `call_structured()`는 구조화 출력·프롬프트 버전·호출 시간·재시도 기록을 남긴다. 실제 SDK의 429·RESOURCE_EXHAUSTED는 `rate_limit`(재시도 없음), 시간 초과·연결 오류·5xx는 `network`(최대 3회, 1초→2초 대기), 형식 오류는 별도 1회 재시도다. 기본 답장 대체 문구와 업무 노드의 오류 처리는 후속 작업에서 채운다. 테스트는 `use_backend(fake)`로 대체한다.
- 일정(캘린더) 도구 작업 때 AI가 `.work/design/api-choice.md`의 '일정 도구 추천 후보'를 요청자에게 추천한다. Calendar는 도구 2용으로 유지하며, 후보 API는 채택 확인 후 추가한다.

## 5. 그래프 노드·흐름 (공통 부분)
마지막 갱신: 2026-11-10

- `app/graph/build.py`·`routing.py`에 계약의 10개 노드·모든 전이를 연결했다(계획 2절, 2026-11-09). 아직 채우지 않은 업무 노드(`load_memory`·`make_quote`·`reflect`)는 입력 상태를 유지하는 빈 틀이고, `finish_failed`는 종료 이유만 정한다. 알림 수신 서비스가 `processed_messages`를 그래프 실행 결과에 연결한다(계획 7절).
- 계획 8절(2026-11-10): `analyze_email`은 LLM 1회로 `intent`(general/deal/ignore)와 근거 한 문장을 받아 `selected_tool`(`draft_replies`/`extract_deal_terms`/없음)·`tool_reason`을 정하고 `tool_select` 기록을 남긴다. general이면 `reply_mode="general"`, ignore면 `end_reason="ignored"`. `draft_replies` 노드는 도구를 `TOOLS`로 부르고 `tool_call`·`tool_result`·`tools_called`를 남기며, 성찰이 실패로 남긴 `reflection.feedback`을 도구에 넘긴다. `save_pending`은 `candidates`를 `reply_candidates`(`status="pending"`)에 저장한다.
- 오류 처리(`app/graph/nodes/common.py`의 `failure_update`): 한도 오류는 재시도 없이 대체 후보·`needs_review`·`notice="rate_limit"`·`step_status="rate_limit"`으로 `save_pending`에 가고(성찰 건너뜀), 통신 실패는 `call_structured()`가 2번 더 시도한 뒤에도 실패하면 `step_status="failed"`로 실패 종료한다. 둘 다 `errors`와 `error` 기록을 남기고, 재시도 횟수(`attempts - 1`)를 `call_retries`에 더한다. 10·11의 노드도 이 함수를 쓴다. 도구를 부르는 노드는 같은 파일의 `call_tool()`(`tool_call`·`tool_result` 기록, `tools_called`·`call_retries`, 실패면 `failure_update`)과 `retry_feedback()`(성찰의 `retry_target`이 그 노드일 때만 `feedback`)을 쓸 수 있다(10에서 더함). 노드 안에서 DB는 `app/runlog/logger.py`의 `current_database()`로 연다.
- 흐름: `load_memory` → `analyze_email` → (일반) `draft_replies` / (거래) `extract_deal` → `check_required` → (빠짐) `draft_followup` / (다 있음) `make_quote` → `draft_replies` → (성찰 켬) `reflect` ↺ 재실행 → `save_pending` → 끝. 실패는 `finish_failed`, 처리 안 함은 바로 끝. 승인·발송은 그래프 밖(`app/services/approval.py`).
- 종료: `awaiting_approval`(정상) · `followup_question`(추가 질문) · `ignored` · `failed`. 성찰 재실행 한도를 넘으면 '확인 필요' 표시로 끝냄(대체 경로).
- 거래 경로 노드를 채웠다(계획 10절, 2026-11-10). `extract_deal`은 거래 항목을 `deal_terms`에 넣고(도구 선택 기록은 `analyze_email`이 남김), `check_required`는 `get_required_fields()` 결과를 `required_fields`에, 빠진 키를 `missing_fields`에 넣고(빠지면 `reply_mode="followup"`), 실행마다 `deal_terms` 표에 한 줄(거래 항목·빠진 항목·출처)을 저장하며 `required_source`와 다음 도구(`draft_followup_replies`/`create_quote`)의 `tool_select` 기록을 남긴다. `draft_followup`은 재질문 후보를 `candidates`에 넣는다. 추출이 통신·형식 재시도를 다 쓰면 `finish_failed`(`end_reason="failed"`), 한도 오류면 대체 후보로 `save_pending`(성찰 건너뜀). 성찰이 이 노드를 다시 실행하게 하면 `reflection.feedback`을 프롬프트에 더한다.
- `start_run()`이 사용자 설정·시험 옵션으로 성찰 여부를 정하고 실행을 시작한다. `traced_node`가 노드 앞뒤·변경 필드·전이·소요 시간·예외 종류를 `runs`·`run_events`에 남긴다. 업무용 성찰 감지·수정 본문은 아직 없다.
- 알림 → 그래프 연결(계획 7절, 2026-11-10): 같은 사용자 알림 처리를 단일 프로세스 안에서 직렬화하고, `(user_id, gmail_message_id)` 유일 제약을 통과한 메일만 `thread_messages`에 저장해 `start_run(mode="live")`을 부른다. 시작 입력의 메일·스레드 ID·사용자 성찰 설정을 기존 진입점이 채운다. 결과의 `run_id`·`notice`를 처리한 메일에 연결하고 승인 대기/추가 질문 → `awaiting_approval`, 처리 안 함 → `ignored`, 실패 → `error`로 남긴다. 모든 Gmail 조회가 성공한 뒤에만 `gmail_watches.history_id`를 옮긴다. Gmail 오류는 `last_error`에 원문 없이 남기고 다음 알림에서 저장된 메일을 건너뛰어 이어 읽는다. 로그아웃·재로그인 필요 상태의 알림은 처리하지 않는다. 계약의 `BackgroundTasks`는 프로세스 내 작업이므로 재시작 중 작업 복구나 만료된 historyId의 전체 동기화는 구현하지 않았다.

## 6. 시험·평가
마지막 갱신: 2026-11-10

- 계획 2절: `tests/fakes/llm.py`로 가짜 LLM을 주입해 그래프 완주·일반/거래/추가 질문/무시/실패/성찰 재실행 전이·노드별 소요 시간·프롬프트 버전 기록을 확인한다. LLM 한도 오류와 통신 실패, 형식 오류의 재시도 예산을 구분하고 실제 SDK 예외·감싼 예외도 시험한다. 외부 API 호출은 없다.
- 계획 6절(`tests/test_auth.py`): `tests/fakes/google.py`의 가짜 Google로 로그인 → 토큰 암호화 저장 → 감시 등록, 24시간 지난 감시 재등록(화면 요청 포함)·접근 토큰 갱신, 다른 사용자 행·위조 세션 쿠키 거부, 갱신 토큰 만료·감시 등록 실패 안내, 로그아웃 중지, 설정 누락을 확인한다. 실제 `GoogleClient`는 동의 주소(PKCE)와 watch 요청 본문만 네트워크 없이 확인한다.
- 계획 7절(`tests/test_gmail_push.py`): 가짜 Gmail SDK 응답으로 새 메일 → 실제 그래프·가짜 LLM → 후보 저장, 중복·동시 알림 1회 처리, 무시할 메일 분류, 사용자별 격리, 같은 스레드·페이지 이어 읽기, Gmail 기록/메일/페이지/본문 조회 실패 후 다음 알림에서 재개, 감시·토큰 갱신, 그래프 실패 상태 연결, OIDC 우선·비밀 토큰·위조/형식 오류 거부, MIME/HTML 변환을 시험한다. ASGI 전송 메시지를 직접 확인해 그래프가 대기 중일 때 이미 204 응답 본문 전송이 끝났음을 검증한다. 실제 Gmail·Gemini 호출은 없다.
- 계획 8절: `tests/test_mail_analysis.py`가 가짜 LLM으로 일반 문의 → 후보 2~3개 저장, 후보 개수 오류 재시도, 거래 메일 → 거래 경로, 처리 안 함, 한도 오류(분석·후보 각각) → 대체 후보와 표시, 통신 실패 → 재시도 뒤 성공·실패 종료, 성찰 피드백 전달을 시험한다.
- 계획 10절: `tests/test_deal.py`가 가짜 LLM으로 필수 항목이 다 있음 → 견적서 경로, 납기 빠짐 → 납기를 묻는 재질문 후보, 추출 실패(통신·형식) → 실패 종료, 한도 오류(추출·재질문 각각) → 대체 후보·성찰 건너뜀, 후보 개수 오류 재시도, 성찰 피드백 전달, 빠진 항목 판정 규칙, 기록에 본문이 남지 않음을 시험한다.
- `tests/test_graph.py`의 흐름 시험은 전이만 보도록 답장 후보·거래 노드를 가짜로 바꿔 끼운다.
- 실행 기록 화면·내보내기(계획 14절, R-12, 2026-11-10): `GET /runs`(본인 실행 목록)·`GET /runs/{run_id}`(노드 전이·도구 선택과 이유·도구 호출·오류·재시도·소요 시간을 `seq` 순서로, 오류·재시도 줄 강조)·`GET /runs/{run_id}/export`(계약 8.2절 `.jsonl`, `docs/test-records/`에 올림). 화면과 파일 모두 `app/runlog/mask.py`로 이메일·이름·전화·사업자번호·실제 메일 본문을 가린다. 본인 확인은 `app/web/deps.py`의 `current_user_id`(세션 `user_id`, 없으면 `/login`)로, 세션에 넣는 일은 로그인(6)이 한다. 지표 계산은 17.
- `/healthz`·기본 화면·로컬 정적 파일, DB 16개 표·사용자별 중복 방지·UTC 저장·Postgres JSONB 정의를 검사한다. 성찰 전후 평가 지표와 실제 API 시험·보고서는 아직 없다.
- 같은 시나리오를 다시 돌릴 때의 편차보다 큰 차이만 개선으로 본다. [Past work: aio3]

## 7. 배포
마지막 갱신: 2026-11-10

- Render 배포(2026-11-10, 계획 4절): 웹 서비스 `https://aio3-gmail-quote.onrender.com`(무료, Singapore, `main` 병합 시 자동 배포), `/healthz` 응답 확인(요청자). 빌드 `uv sync --locked`, 시작 `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`. 넣은 환경변수: `DATABASE_URL`(Internal 주소)·`GEMINI_API_KEY`·`SESSION_SECRET`·`REFLECTION_ENABLED_DEFAULT`·`APP_BASE_URL`. Google 값과 `TOKEN_ENCRYPTION_KEY`는 아직 없음.
- Render Postgres: 무료, Singapore(웹 서비스와 같은 지역), 2026-11-10 만듦 → 30일 뒤 2026-12-10경 만료, 14일 유예 뒤 2026-12-24경 삭제(11/19 제출까지는 충분).
- 주의: 15분 동안 요청이 없으면 잠들고 깨는 데 최대 약 1분 걸린다. 재배포·재시작·잠들 때 로컬 파일이 사라지므로 저장은 Postgres에만 한다. 시연 전에 화면을 미리 열어 깨운다.
- 로컬 서버 뼈대는 `uv run uvicorn app.main:app --reload`로 실행한다. `/`→`/inbox`와 `/healthz` 정상 응답을 확인했다. 키 없이 기본 화면을 열 수 있고, `DATABASE_URL`이 비면 커밋 제외된 `app/db/local.sqlite3`를 쓴다. Postgres 연결용 드라이버·없는 표 생성은 준비됐으며 실제 Render 연결 시험은 후속 작업이다.
- 환경변수는 `docs/CONTRACT.md` 11절을 기준으로 `.env.example`에 이름과 설명만 둔다. 값은 로컬 `.env`와 Render 환경변수에 두고 Codex에는 키를 넣지 않는다.
- LLM·OAuth: `GEMINI_API_KEY`, `GOOGLE_OAUTH_CLIENT_ID`·`GOOGLE_OAUTH_CLIENT_SECRET`·`GOOGLE_OAUTH_REDIRECT_URI`.
- Gmail 푸시: `GMAIL_PUBSUB_TOPIC`, OIDC 확인용 `PUBSUB_PUSH_AUDIENCE`·`PUBSUB_PUSH_SERVICE_ACCOUNT`, 대체 비밀 토큰 방식일 때만 `PUBSUB_PUSH_TOKEN`.
- 앱 설정: `DATABASE_URL`(Postgres 접속 주소, 로컬에서 비우면 SQLite 파일), `TOKEN_ENCRYPTION_KEY`(Google 토큰 암호화 키), `SESSION_SECRET`(세션 쿠키 서명 키), `APP_BASE_URL`(서비스 주소), `REFLECTION_ENABLED_DEFAULT`(성찰 기본값).
- 로그인(계획 6절): `GOOGLE_OAUTH_*`·`GMAIL_PUBSUB_TOPIC`·`TOKEN_ENCRYPTION_KEY`(Fernet 키)·`SESSION_SECRET`이 모두 있어야 로그인 버튼이 켜진다. 두 키는 `.env.example`의 명령으로 만들고, `TOKEN_ENCRYPTION_KEY`를 바꾸면 모두 다시 로그인해야 한다. `APP_BASE_URL`이 `https://`면 세션 쿠키를 HTTPS 전용으로 보낸다(Render).

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
마지막 갱신: 2026-11-10

- 세팅 단계는 `.work/FLOW.md` 순서로 진행한다. 7단계까지 모두 마쳤다. 다음 과제는 템플릿 레포 `doomdiver100T/aio-team-template`([공통] 파일, [과제별] 빈 틀·최소 실행 틀)의 README '이 템플릿으로 새 과제 시작하기'에서 시작한다(Template repository 켜 둠). 작업량 기준 100KB·도구 1회 크기는 기록을 보고 그대로 두었다(`.work/RULES.md` 8절 5번). 세팅 진행기록은 `.work/STATUS.md`.
- [공통] 파일은 두 레포에서 같게 둔다(읽음 확인 코드 줄만 다름). 이 레포의 고유 값(레포 주소 등)은 [공통] 파일에 쓰지 않고 `.work/TASK.md`에서 가리킨다(RULES 2절 4번의 Issue 주소가 그 예).
- 팀원은 ChatGPT(Codex)로 작업을 맡기고, 세팅 단계는 Claude가 한다. 모두 PR로 올린다. Codex는 새 Codex Cloud의 환경 `aio-03-p2-team3`(워크스페이스 공유, 팀원 모두 GitHub 연결 마침)를 쓴다. 작업은 ChatGPT 왼쪽 `…` → Codex → Cloud · Choose environment에서 시작하고, Codex는 `AGENTS.md`를 자동으로 읽으므로 요청 문구에 그 파일을 읽으라고 쓰지 않는다. 요청 문구에 적지 않아도 `AGENTS.md`의 'Codex가 꼭 할 일'대로 검사·테스트·push·PR까지 하고, Issue는 `Issue: #번호`만 적으면 GitHub에서 본문을 읽는다(환경에 `api.github.com` 허용 뒤, 못 읽으면 본문을 붙임)(팀원 절차: 요청 → PR 확인 → 병합), 답에 PR 링크가 없으면 같은 작업에 후속 요청으로 연다. 연결·요청 문구는 `docs/CHATGPT_GUIDE.md`.
- Codex 환경에는 API 키를 넣지 않는다. Codex에서 도는 테스트는 가짜 응답으로 하고, 실제 API 시험은 로컬과 Render에서 한다.
- 병합: 승인 없이 PR을 연 사람을 포함해 누구나 병합한다. `main`에는 Ruleset 'main 필수 검사'(`rules-check`·`tests`·`pr-check` 필수, 승인·strict 없음)가 있어 검사 통과 전에는 병합되지 않는다. Claude는 병합하지 않고, Codex는 팀원이 요청할 때 검사 통과 뒤에만 병합한다. 병합한 브랜치는 지우지 않는다.
- 기능이 둘 이상 섞인 요청과 '작업 분배'·'작업 배분'·'작업 나누기' 요청(세팅 단계 작업 제외, KB 재기·FLOW·STATUS 안 씀)은 먼저 `docs/plans/<작업명>.md`를 PR로 올리고, 그 AI가 하위 작업마다 Issue(`<작업명>#N <절 제목>`)를 만든다(못 만들면 요청자가 만듦). 절마다 '선행 작업'·'하는 사람(Codex/사람/Claude)'을 적어 선행 작업이 없는 절은 동시에 하고, 맡는 사람은 Issue Assignees에 자신을 넣고 하위 작업마다 새 작업으로 한다(2026-11-09, `.work/RULES.md` 7절, 형식 `docs/plans/README.md`).
- PR '설명' 칸에는 '작동 방식(발표용)'(구현 방식 2~4문장)도 적고 마지막 답에서 요청자에게 따로 짚어 안내하며(Codex·Claude 모두), 계획·설계서·시험 보고서·PR은 요구사항을 `docs/REQUIREMENTS.md`의 R-ID로 가리킨다(2026-11-09, `.work/TASK.md` 이 레포의 규칙).
- 작업 완료 답변에는 별도 요청이 없어도 다음 작업 1~3개의 담당·시작 조건·계획 절·Issue를 안내하고, Codex 하위 작업은 새 작업용 요청문을 함께 준다. 완료 여부를 확인하지 못했으면 `미확인`으로 표시한다(2026-11-09, `AGENTS.md` 5번·`.work/RULES.md` 5절 8번).
- 담당(2026-11-10): 공통 기반(공통 계약, 서버·DB·배포, Google 로그인·Gmail 알림 수신)과 검토 기능은 김민성, 캘린더 연결 기능은 정원철, 이미지→견적서 기능은 임석원. 김진혁은 Assignees가 비어 있는 Issue에서 배정받는다. 담당은 Issue Assignees로 보고, 프로젝트를 마친 뒤 PR 내역으로 README에 정리한다(`.work/TASK.md`). [Request]
- 실행 환경: Python 3.12, uv. 설치 `uv sync`, 테스트 `uv run pytest`, 패키지 추가 `uv add <패키지>==<버전>`. 서버는 로컬 `uv run uvicorn app.main:app --reload`, Render `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`로 실행한다. 자세한 것은 README '실행 방법'.
- 규칙 검사: `python3 .work/check.py`. PR 전에 통과시킨다(테스트는 따로 `uv run pytest`).
- CI: `.github/workflows/rules-check.yml`. PR과 `main` 변경마다 `rules-check`(규칙 검사, 파일 지도에 없는 파일도 오류)와 `tests`(`uv sync --locked` 뒤 `uv run pytest`)가 따로 돈다. `uv.lock`이 `pyproject.toml`과 어긋나면 `tests`가 실패한다. PR에서는(본문을 고쳐도) `pr-check`도 돌아 PR 본문 '읽은 파일' 칸의 읽음 확인 코드(RULES.md·TASK.md·이 문서)와 '최신 흐름 갱신' 칸(이 문서를 안 고쳤으면 `해당 없음 — 이유`)을 본다.
