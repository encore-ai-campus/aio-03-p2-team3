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
마지막 갱신: 2026-11-13 · 메일 도구 연결과 사용자 화면 연결의 차이 검토

- 서비스: 사용자별 Gmail 메일을 분석해 답장 후보 2~3개를 만들고, 사용자가 고른 후보만 같은 스레드로 보낸다. 거래 메일은 필수 항목이 빠지면 재질문 후보, 갖춰지면 국내 견적서 또는 PI·PO·CI·PL 초안을 만든다. 문서 확정과 메일 발송 승인은 별개다.
- 현재 지원하는 실행 방식은 아래와 같다. 모든 AI 호출은 OpenAI Responses API를 쓰며 기본 모델은 `gpt-6-luna`, 변경값은 `OPENAI_MODEL`이다(#127·#152·#159~#163).

| 실행 방식 | AI 키와 호출 위치 | Gmail 수신 |
|---|---|---|
| `server` + `stored_key` | 본인이 `/settings`에 등록한 암호화 DB 키, 서버 호출 | 공용 Google OAuth·Pub/Sub |
| `server` + `local_worker` | 연결한 본인 PC의 개인 환경 파일 키, PC 호출 | 서버가 수신·승인 발송, PC가 AI 처리 |
| `local` | 검증된 지정 소유자의 `.env` 키, 본인 PC 호출 | 개인 OAuth·루프백 콜백, 30초 간격 history 수집 |

- 화면: `/inbox`는 본인 메일의 처리 중·승인 대기·발송·오류를, `/threads/{thread_id}`는 원문·후보·처리 상태와 실행 기록 링크를 제공한다. 받은 메일 목록은 90초 간격 갱신, 스레드는 처리 중일 때만 자동 갱신한다(#85·#105). `/about`·`/privacy`·`/terms`는 비로그인 공개 페이지다(`app/web/routes/pages.py`).
- 독립 문서 API `/api/trade/{pi|po|ci|pl}`는 직접 입력/AI 추출 → 수정 → 검토 → 승인·취소 → PDF/XLSX 발급을 제공한다. 이 승인은 Gmail을 발송하지 않는다. 해당 API 구현(#112) 뒤 개발용 React 로그인·설정과 PI 작성/검토/발급 화면을 연결했다(7절). PO·CI·PL 화면은 아직 없다. 문서별 `agent.py`는 구조화 추출 함수이며 독립 StateGraph나 마스터 챗봇은 아니다.
- 메일 그래프는 `make_quote` → `create_trade_document`로 네 무역 문서 초안을 저장한다. 그러나 기존 스레드 화면의 `thread_view()`는 후보의 `trade_doc_id`를 전달하지 않고 국내 `quote_id`만 링크로 표시한다. 따라서 무역 후보가 생성돼도 기존 화면에서 문서 검토·발송 승인으로 갈 수 없다. 임시 PostgreSQL·가짜 LLM으로 PI 후보 2개 생성과 링크/승인 폼 0개를 재현했다. 화면/JSON 연결은 전환 계획 19절(#147)에서 보완·검증해야 하며, 백엔드 발송 서비스 시험 통과를 사용자 화면 완주로 표시하지 않는다.
- 과제 R-01·R-02·R-09·R-10의 실행 근거는 메일 StateGraph다. 독립 문서 작성/추출 API는 그 그래프를 실행하지 않으므로 PI 폼 완주만으로 성찰·기억·도구 선택을 시연했다고 볼 수 없다. 마스터 챗봇·멀티 에이전트는 과제 필수 조건이 아니다. 대표 흐름과 실제 배포 검증의 차이는 [서비스 연결 검토](plans/react-supabase/PROGRESS.md#서비스-연결-검토2026-11-13)를 참고한다.
- Google 로그인·암호화 토큰 저장·감시 갱신과 푸시 수신은 구현됐다(#79·#81). 로컬 Gmail 수집은 Pub/Sub·watch/stop 없이 동작한다(#160). 실제 운영 연동의 확인 범위는 6·7절과 #157에서 구분한다.
- 남은 범위: 필수 항목 출처는 현재 `app/quote/required_fields.py`의 `source="config"`, `evidence=[]`다. 규칙 근거 RAG는 gmail-quote-mvp 22절의 후속 작업이며, 일정 도구 후보는 `.work/design/api-choice.md`의 '일정 도구 추천 후보'에 있다. 일정 도구의 LLM 입력은 제목 없이 바쁜 시간대만 전달하는 범위다.
- 상세 위치: [공통 계약](CONTRACT.md) 6·9·10·15·16절, [독립 문서 API](trade-api.md), [로컬 실행 계획](plans/local-openai-execution.md) 1~5절. 계획 머리말과 README 일부의 '미구현' 표현은 작성 당시 기록이며, 현재 지원 범위는 위 표처럼 코드와 병합된 구현 PR을 대조했다.

## 3. 그래프 상태·기억 (공통 부분)
마지막 갱신: 2026-11-12 · 상태·기억의 현재 계약과 경계 요약

- 정의 원본: `app/graph/state.py`의 `AgentState`·`initial_state`, [공통 계약](CONTRACT.md) 2·3.4·7·12.4절. 입력(`run_id`·`user_id`·`email`), 기억(`thread_context`·`long_term`), 판단(`intent`·`selected_tool`), 거래·결과(`deal_terms`·`required_fields`·`missing_fields`·`candidates`·`quote_draft`·`trade_doc_draft`), 성찰·오류·횟수·종료 상태를 분리한다.
- `deal_terms`는 국내 `DealTerms`와 무역 `TradeDocTerms`를 `doc_kind`로 구분한다(없으면 `quote`). 무역 수량·금액은 Decimal 문자열이다. 정확한 필드·기본값은 코드와 계약 2·15.2절에 있다(#107·#112).
- `tools_called`·`reflection_history`·`errors`·`call_retries`는 누적 리듀서다. 통신·형식 재시도(`call_retries`)와 성찰 재실행(`reflection_retries`·`reflection_retries_by_type`)은 따로 센다. `notice`에는 사용자 키와 개인 PC 실행 오류 안내도 있다(#91·#152·#162).
- 기억 구현: `app/services/memory.py`가 본인·같은 스레드의 요약/미요약 원문과, 본인 회사·단가·선호 및 같은 상대의 최근 거래 5건을 읽는다. 현재 메일 조건이 우선하며 과거 수량·단가·납기를 이번 거래로 복사하지 않는다. 다른 사용자·상대방의 기억과 미래 메일은 제외한다(#88).
- 긴 스레드는 현재 메일 포함 8개 또는 본문 12,000자를 넘을 때 최근 원문 4개를 남겨 누적 요약한다. 원문은 DB에 보존하고 성공한 요약만 커서를 갱신한다. AI 대기는 DB 트랜잭션 밖에서 수행하며, 대기 중 요약/커서가 바뀌었으면 덮어쓰지 않는다(#162).
- 원문·확인 조건·직전 결과는 `save_pending`에서 저장한다. 장기 거래/문체 기억은 본인 승인·발송 성공 뒤 실제 수신자를 기준으로 저장한다. 기억 저장만 실패하면 발송 성공을 유지하고 자동 재발송하지 않는다.

## 4. 도구(API 연동) (공통 부분: 도구 스키마)
마지막 갱신: 2026-11-12 · OpenAI·문서·개인 실행기 구현 상태 요약

- 공통 AI 진입점은 `app/llm/client.py`의 `call_structured()`와 `app/services/openai_keys.py`의 `user_openai()`다. 메일·요약·성찰과 네 문서 추출이 같은 OpenAI 모델/구조화 출력을 쓴다. `stored_key`는 Fernet으로 암호화한 본인의 OpenAI 키를 읽고, `local`·`local_worker`는 지정 소유자의 개인 파일 키를 사용한다. 키 누락·복호화 실패·PC 오류 때 다른 사용자/서버 환경 키로 대체하지 않는다(#127·#152·#159·#162).
- 호출 예산: SDK 자동 재시도 0, 호출 제한 20초. 429는 재시도 없이 한도 안내, 통신/5xx는 최대 3회(1·2초 대기), 형식 오류는 별도 1회 재시도다. PC 방식의 재시도는 서버 `app/worker/adapter.py` 한 곳에서 기존 예산과 전체 120초 기한으로 관리한다. 짧은 HTTP/예외 코드는 실행 기록에 남기고 키·원문은 남기지 않는다(#98).
- 등록 도구 7개: `draft_replies`, `extract_deal_terms`, `check_required_fields`, `draft_followup_replies`, `create_quote`, `create_trade_document`, `send_email`(`app/tools/registry.py`). 필수 항목은 `get_required_fields()` 한 곳에서 받고, 답장 후보는 금액·문서번호를 복사하지 않고 첨부 문서를 안내한다. `send_email`은 승인 경로에서만 호출한다. 프롬프트 버전 원본은 `app/prompts/VERSIONS.md`다.
- 국내 견적: 합의 단가 → 이름·단위가 같은 단가표 → 사용자 입력 순서로 채운다. 누락 단가는 `needs_price`, 완료는 `ready`이며 정수 금액·부가세 10% 버림·30일 유효기간과 한글 PDF를 지원한다. 코드 `app/quote/`, `app/web/routes/quotes.py`; 상세는 계약 4·9·12.2절(#89).
- 무역 문서: `app/trade/{pi,po,ci,pl}/`가 도메인 업무를, `common/`·`review/`·`settings/`가 공유 계산/출력·검토·설정을 담당한다. 직접/AI 입력은 같은 계산·검증을 거친다. CI는 승인된 PI의 특정 버전·거래 사실을 보존하고 PL은 원본/계산 합계의 별도 승인을 요구한다. 검토는 문서 revision·내용 해시·회사/계좌/이미지를 고정한 뒤 승인 파일을 저장한다. 루트 호환 입구는 제거됐다(#107·#112·#114). 상세: 계약 15·16절, [API 안내](trade-api.md).
- Gmail 문서 발송은 `app/services/approval.py`의 `send_approved_quote()`·`send_approved_trade_document()`가 담당한다. 무역 문서는 `ready`·PL 합계 승인·CI PI 원문 근거·직인을 확인하고, 발송 중 문서 변경과 중복 승인을 막는다. 성공 때 문서·후보·메일을 발송 상태로 바꾸고 같은 메일의 다른 후보는 종료한다. 발송 자체는 자동 재시도하지 않으며 시간 초과/5xx는 보낸편지함 확인 후 명시적 재승인 대상이다(#85·#107).
- 개인 PC 실행: `app/worker/{protocol,service,adapter,pc}.py`가 설치된 구조화 정의·모델·소유자·장치·시도/기한을 검증한다. 서버는 키를 받지 않고 큐 결과를 암호화해 전달 후 소비/해제/기한에 지운다. 미완료/거부된 PC 결과로 후보·문서를 저장하지 않으며 만료된 임대는 자동 재배포하지 않는다. 장치 API는 메일 승인·발송·파일 권한을 갖지 않는다(#161·#162). Windows 자격증명은 `credentials.py`의 현재 사용자 DPAPI·보호 DACL, macOS/Linux는 소유자·600 권한으로 보호한다(#163). 상세: 계약 6절.

## 5. 그래프 노드·흐름 (공통 부분)
마지막 갱신: 2026-11-12 · 현재 전이·성찰·오류 종료 요약

- 진입점은 `app/graph/run.py`의 `start_run()`, 10개 노드·전이는 `app/graph/build.py`·`routing.py`, 업무 본문은 `nodes/`다. 핵심 흐름은 다음과 같다(상세: 계약 3절).
  - `load_memory` → `analyze_email` → 일반 `draft_replies` / 거래 `extract_deal` → `check_required` → 누락 `draft_followup` / 충족 `make_quote` → `draft_replies`.
  - 후보 생성 뒤 성찰을 켰으면 `reflect`에서 필요 노드를 재실행·재검증하고, 마지막에 `save_pending`으로 저장한다. 처리 제외는 즉시 끝나며 실패는 `finish_failed`로 간다. 승인·메일 발송은 그래프 밖이다.
- `make_quote`는 `doc_kind`로 국내/무역 생성 도구를 고르고 본인 회사·계좌·단가 설정과 실행 ID를 문서/후보에 연결한다. 일반·거래·재질문·견적과 무역 경로 모두 구현돼 있다(#89·#107). 결과는 `awaiting_approval`·`followup_question`·`ignored`·`failed`로 구분한다.
- 성찰은 규칙으로 환각·도구 선택 오류·필수값 누락·응답 불일치를 찾고, 문제가 있을 때만 `reflect_fix`를 호출한다. 유형별 한도는 환각 2·도구 1·누락 1·불일치 2, 전체 3회다. 한도 초과·성찰 자체 오류는 확인 필요 후보로 끝낸다(#91). 새 사용자 기본값 → 사용자 설정 → 실행 옵션 순으로 성찰 여부를 정한다.
- 직접 AI 호출의 한도 오류는 자동 재시도 없이 기본 후보 1개·`needs_review`·`rate_limit` 안내로 저장하고, 통신/형식 오류는 호출 예산 소진 후 실패한다(`nodes/common.py`). PC 실패는 `save_pending`의 완료 확인과 `start_run`의 안전한 오류 안내로 후보 저장을 막는다(#162).
- Gmail 수신은 `app/services/gmail_push.py`의 사용자별 직렬화·메일 유일 제약으로 중복을 막고, 해당 수집의 모든 Gmail 조회가 성공한 뒤에만 history를 갱신한다. 프로세스 내 `BackgroundTasks` 방식이며 서버 재시작 중 작업 복구·공용 history 만료의 전체 재처리는 구현 범위 밖이다(#81). 로컬 history 만료는 전체 재처리 대신 재로그인을 안내한다(#160).
- `app/runlog/`가 노드·전이·도구·성찰·오류/재시도·소요 시간을 기록한다. `/runs`·`/runs/{run_id}`·`/export`는 본인 기록만 개인정보를 가려 제공한다. 실행 종료 이유와 승인 뒤 발송 상태는 구분한다. 상세: 계약 8절, `app/web/routes/runs.py`.

## 6. 시험·평가
마지막 갱신: 2026-11-13 · PI 단계형 작성·누락 질문과 검토/발급 검증

- React PI: `frontend/`의 `npm test`는 원문 추출 후 빈칸만 질문·완료 단계 건너뛰기·미확인 상품군/0원 샘플 구분·십진수 입력 보존을 확인한다(4개 통과). lint/build·규칙 검사와 전체 `uv run pytest` **917 passed·2 skipped**를 통과했다. 실제 FastAPI·임시 PostgreSQL·가짜 Storage/OpenAI의 브라우저 흐름으로 직접 작성/원문 누락 보완/품목 표 수정/재검토/승인, 발급 PDF·XLSX 해시 일치와 409 때 입력 보존을 확인했다. 1440·768·390px 화면에서 배치와 가로 넘침도 확인했다. 실제 OpenAI·운영 Supabase DB/Storage 연결 검증과 구분한다. 기존 전환 범위·제한은 [전환 진행 현황](plans/react-supabase/PROGRESS.md).

- 기준 코드 `c6b1600`의 최근 병합 PR #163은 Linux 전체 **829 passed·4 skipped**를 기록했다(선택 PostgreSQL 모듈 2개·Windows 전용 검사 2개 제외). GitHub [CI 실행 43167274015](https://github.com/encore-ai-campus/aio-03-p2-team3/actions/runs/43167274015)의 `rules-check`·`tests`·`pr-check`·`windows-worker` 모두 성공을 직접 확인했다. Windows 작업은 자격증명·실행기·실제 HTTPS 프로세스 시험을 실행한다. 자동/모의 검증 통과와 실제 API/운영 검증은 별개다.

| 작업 영역 | 확인할 시험·근거 |
|---|---|
| 메일·승인·견적·성찰·기억 | `tests/test_{auth,gmail_push,mail_analysis,deal,approval,quote,reflect,memory}.py`, `test_graph.py` |
| OpenAI·로컬·PC·Windows | `test_llm.py`, `test_openai_keys.py`, `test_local_openai.py`, `test_local_gmail.py`, `test_worker_{queue,execution,process,credentials}.py` |
| 무역 계산·발급·버전·회귀 | `tests/test_trade_*.py`, `test_pi_*.py`, [무역 검증 기록](test-records/20261111_trade_domain_api.md) |
| 실제 임시 PostgreSQL | `uv run --with pgserver==0.1.4 pytest tests/test_worker_postgres.py tests/test_trade_postgres.py -q`. PR #162의 두 모듈 8개 통과는 모의 DB가 아닌 임시 PostgreSQL 결과다. |

- 시험 실행기 `app/evaluation/`는 정상 일반/견적·정보 부족·Gmail 오류·OpenAI 한도·도구 오판·환각의 7개 시나리오를 성찰 끔/켬으로 비교한다. 지표는 완료율·도구 선택 정확도·응답 일관성·평균 재시행 횟수다. 고의 주입은 `detail.injected`로 표시하고 실제 API 결과와 구분한다(#92·#93). 실행 조건·명령은 [TEST_REPORT](TEST_REPORT.md) 2~5절, 실제 측정/보고서는 gmail-quote-mvp 18·19절이다.
- 실제 API 확인 이력은 [2026-11-10 일반 문의 기록](test-records/20261110_live_general_result.md)(#97)에 있다. 당시 Gmail·Gemini로 일반 문의의 후보 생성→승인 발송을 확인한 결과이며, OpenAI 성능이나 모든 시나리오 검증 결과로 쓰지 않는다. 현재 OpenAI 전환 후 지표·최종 보고서 완료는 이 근거만으로 확인되지 않는다.
- 개인 PC 실제 연결·키 교체/삭제·두 사용자 과금 프로젝트·Render 종단 간 확인은 [#157](https://github.com/encore-ai-campus/aio-03-p2-team3/issues/157)(조회 시 open), 로컬 실행 계획 5절에서 미확인이다. 코드/모의 HTTP/브라우저/Windows CI 통과를 이 완료로 표시하지 않는다.
- 과거 시험별 상세 결과와 구현 경위는 각 병합 PR, `docs/test-records/`, [축약 전 문서](https://github.com/encore-ai-campus/aio-03-p2-team3/blob/c6b16007f824450fc5cfd23e77da877beaf87930/docs/PROJECT_CONTEXT.md)에 보존돼 있다. KE KOREA 원본 동일성·알려진 오류 점검 기록은 `test-records/20261110_kekorea_port_err_check.md`다.

## 7. 배포
마지막 갱신: 2026-11-13 · React 빌드·같은 출처 제공 선행 작업과 후속 검증 분리

- Render 설정 기록(2026-11-10): `https://aio3-gmail-quote.onrender.com`, 무료·Singapore·main 병합 시 자동 배포, 빌드 `uv sync --locked`, 시작 `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`. 당시 설정 기록이며 이번 문서 갱신에서 현재 운영 상태를 재확인하지 않았다.
- 계획 21.1절(#149)은 6·7절을 선행으로 UI 개발과 병행한다. `render.yaml`·`scripts/render-build.sh`가 `uv sync --locked` → `npm ci --include=dev` → `npm run build`와 기존 서버 시작을 연결한다. FastAPI는 `frontend/dist`만 `/app/`에서 제공하며 상세 주소는 `index.html`로 복구하고 누락 자산은 404로 반환한다. `/api`·Google callback·Gmail Pub/Sub·공개 약관·기존 `/static`과 `/`→`/inbox`는 유지한다. 빌드가 없는 개발 환경에서도 서버는 동작하고 UI만 503이다. `frontend/` 파일은 수정하지 않았다. Dashboard 관리 서비스에는 README 절차대로 Build Command/Node 버전을 적용해야 하며 실제 Render 설정·배포 커밋·운영 응답은 미확인이다. 전체 UI 통합 검증/진입 전환은 20절 뒤 21.2절, 실제 운영 전환은 사람의 22절이다. #149는 후속 검증까지 열어 둔다.
- 배포 기반 검증은 전체 PostgreSQL `uv run pytest` 923 passed·2 skipped, 규칙 검사 경고 0개, 프론트 lint/test/공개값 검사·실제 빌드와 Chromium smoke를 통과했다. 상세 주소/자산·콜백/알림 경로와 서버 비밀값 제외 근거는 [진행 현황](plans/react-supabase/PROGRESS.md)의 21.1절에 있다. 전체 UI 완주·실제 운영 성공과 구분한다.
- 앱 DB는 PostgreSQL 전용이다. `DATABASE_URL`이 비었거나 비PostgreSQL이면 시작을 거부하며 SQLite 자동 생성은 없다. Alembic 대상은 `public`으로 고정해 Supabase `auth`·`storage`를 건드리지 않는다. `20261112_react_worker_merge`가 Supabase 전환/기존 worker 분기를 합친다. 운영 반영 전 DB 백업과 기존 `TOKEN_ENCRYPTION_KEY` 유지가 필요하다. SQLite 등 기존 원본은 `app.db.copy_data`, 회사 이미지/발급 바이너리는 backfill 명령으로 복사·해시 검증하며 원본·바이너리 열은 아직 삭제하지 않았다([전환 계획](plans/react-supabase/PLAN.md) 4·9·10·22절).
- 무료 서버는 15분 미사용 시 잠들 수 있고 재시작/배포 때 로컬 파일을 잃으므로 운영 데이터는 Postgres에 둔다. 2026-11-10 생성한 무료 Postgres는 당시 안내상 12/10경 만료·14일 유예 후 삭제 예정이었다. 현재 요금제·보존 상태는 운영 담당자가 확인한다.
- 서버 `stored_key`는 본인 로그인 후 `/settings`에서 키를 등록한다. 서버 `OPENAI_API_KEY` 대체는 차단돼 있다. `local_worker`는 개인 PC가 켜져 있고 같은 모델/설치 정의로 연결돼 있어야 한다. 메일·문서 입력과 AI 결과는 서버를 거치지만 PC 키는 서버에 전송/저장하지 않는다. 키를 지우거나 PC를 중지해도 이미 외부 API에 전송한 요청의 취소를 보장하지 않는다.
- 로컬 전체 실행은 `AI_RUNTIME=local`·본인 `LOCAL_OWNER_GOOGLE_SUB`·`.env` 키와 `uv run python -m app.local`을 쓴다. 실제 리스너는 `127.0.0.1` 전용이고 공용 Uvicorn/Render 시작은 거부한다. 개인 Google OAuth·루프백 콜백과 별도 로컬 DB를 쓰며 Pub/Sub 토픽 없이 연결한다. 운영 DB·암호화 키·OAuth 비밀값을 개인 PC로 복사하지 않는다(#159·#160·#157).
- 서버+PC 방식은 `uv run python -m app.worker.pc pair`로 본인 HTTPS 서비스와 연결 승인 후 `run`으로 실행한다. 개인 환경 파일·서비스 주소·검증된 본인 Google 식별자를 지정하고, 키 교체 뒤 재시작한다. Windows PowerShell도 WSL 없이 지원한다(#163). 설치·`--env`/`--credentials`·중지·재연결·문제 해결은 [README](../README.md)의 개인 PC 실행 안내에 있다.
- React 앱은 `frontend/`의 JavaScript/Vite이며 개발은 `npm ci` 후 `npm run dev`(`/app`, `/api` 프록시)다. 루트 `.env`의 `FRONTEND_PORT`가 개발 포트이며 비우면 5174, 지정하면 그 포트만 쓴다(사용 중이거나 올바르지 않으면 실패). 로그인 반환 주소는 실제 포트의 `/app/login`과 맞춘다. `/app/settings`에서 회사·거래처·판매/구매 단가·통화별 계좌·로고/직인을 저장한다. 기존 API를 재사용하고 거래처 저장만 추가했다. 실패 입력 보존·조회 취소·이미지 객체 URL 정리를 두며 새 설정은 기존 제안/발급 파일을 바꾸지 않는다. PI는 `/app/trade/pi`·`/app/trade/pi/{id}`에서 작성 방법 선택 → 거래처/판매자/품목/거래 조건 → 전체 확인 → 검토/승인/다운로드로 진행한다. 원문 추출 결과와 설정 기본값을 보존하고 필요한 빈칸만 질문하며, 채워진 내용도 단계별 전체 수정에서 바꿀 수 있다. 품목은 표로 편집하고 규격·할인·샘플은 접어 둔다. 오른쪽 작성 요약은 모바일에서 펼쳐 보고, 전체 문서는 마지막에 한 번만 표시한다. 금액·가격 확인·revision/해시 검토·발급은 기존 서버 API를 그대로 쓴다. 버전 충돌 때 입력을 보존하며 최신본 재조회와 재검토를 안내한다. 고정된 회사 이미지는 소유자·문서·제안 범위 읽기 API로 확인하고, 개인 키 관리는 기존 서비스를 Bearer API로 연결했다. PO·CI·PL/메일/현황 화면은 13~20절, 전체 UI 통합 검증은 21.2절 후속 작업이다.
- Supabase 로그인은 `SUPABASE_URL`의 JWKS로 Bearer 서명·issuer/audience·만료·UUID를 검증해 기존 정수 사용자 ID에 매핑한다. `/api/me`·`/api/gmail/*`·`/api/files*`와 무역/설정 API를 연결했으며 잘못된 Bearer가 쿠키 세션으로 우회하지 않는다. legacy 로그인/CSRF는 전환 기간 유지한다. Gmail 연결은 state·PKCE·같은 Google 공급자 subject를 확인하고, 앱 로그아웃 때 감시를 중지한다(계약 9.1절).
- 첨부·회사 이미지·승인 PDF/XLSX의 bytes는 private Storage, 소유자/참조/해시는 PostgreSQL에 둔다. 모든 형식 업로드 뒤에만 문서 승인 SQL을 확정한다. 발급 객체 재사용·backfill·수동 정리는 같은 객체별 PostgreSQL 트랜잭션 잠금으로 조율하고 삭제 전 참조를 다시 확인한다. 상세 파일 계약/제한/이전 명령은 계약 16.3절과 README다.
- 공용 OAuth·Gmail Pub/Sub·OIDC/대체 토큰은 유지한다. 로컬은 watch/stop을 호출하지 않는다. 문서/설정 API는 Bearer 또는 기존 세션/CSRF로 소유자를 검사하고, 장치 승인과 장치 통신의 기존 CSRF·장치 토큰 계약은 유지한다. 환경변수 원본은 `.env.example`·계약 11절이다. Supabase는 루트 `.env`의 `SUPABASE_URL`·`SUPABASE_PUBLISHABLE_KEY`·`SUPABASE_SECRET_KEY` 세 값으로 설정하며 Vite는 URL과 공개 키만 브라우저에 제공한다. `frontend/.env`와 중복 URL은 제거했고 버킷은 기본 `trade-files`다. 실제 DB 연결용 `DATABASE_URL`은 별도로 필요하다. `frontend/`의 `npm run check:env`로 공개값 전달·비밀값 빌드 제외를 확인한다. 프로젝트·비공개 버킷·Google OAuth 준비는 사용자 확인이며 로컬 Supabase URL/키와 개발 포트를 설정했다. Auth 설정 조회·Google 로그인 시작은 확인했고, 실제 계정 로그인·Gmail·운영 DB/파일 이전은 미확인이다. 현재 로컬 DB는 임시 PostgreSQL이며 실제 DATABASE_URL과 Google/암호화 설정은 별도로 확인해야 한다.
- 운영·실제 API 확인은 #157, [로컬 실행 계획](plans/local-openai-execution.md) 5절과 gmail-quote-mvp 16·18절에 남아 있다. Codex의 역할은 코드/병합 근거·자동/모의 검사·실행 절차 준비까지이며, 테스트용 Google 계정·가상 메일을 쓰고 실제 키 입력·Google 동의/장치 승인·본인 PC 실행·과금/운영 변경은 사람이 한다.

## 8. 문서·산출물 위치
마지막 갱신: 2026-11-13 · 배포 선행 작업·통합 후속 단계 분리

| 무엇 | 위치 | 상태 |
|---|---|---|
| 과제 요구사항 정리(R-ID·D-ID) | `docs/REQUIREMENTS.md` | 있음(2026-11-09) |
| 에이전트 아키텍처 설계서 | `docs/ARCHITECTURE.md` | 초안 있음(최종 코드와 맞춰 20에서 고침) |
| 에이전트 시험 결과 보고서 | `docs/TEST_REPORT.md` | 틀 있음(2026-11-10, 시나리오·판정 기준·시험 환경. 결과는 18·19) |
| 시험 실행 기록(실행마다 한 파일)·실제 API 확인 결과 | `docs/test-records/` | 있음(2026-11-10, #62 1번 일반 문의 흐름: 실행 기록 3개와 결과 문서) |
| 큰 작업의 계획 파일 | `docs/plans/gmail-quote-mvp.md` (형식: `docs/plans/README.md`) | 있음(Gmail 견적 MVP 구현 계획) |
| 개인 PC .env 키로 로컬/Render AI 실행 지원 | `docs/plans/local-openai-execution.md` | 1~4절 로컬 키·Gmail 수집·장치/큐·PC 실행기/기존 AI 연결 구현. 실제 키·Render 연동은 사람의 5절에서 미확인 |
| KE KOREA 무역서류 로직 이식 계획 이력 | `docs/plans/kekorea-port.md` | 1~6절 완료, 참고 이력 |
| KE KOREA 원본 사본(참고 이력, 읽기 전용) | `reference/kekorea/` (담은 것·바꾼 것·원본 테스트 실행법은 그 폴더 README) | 완료한 이식의 원본(ai-agents `8d397a1`, 앱에서 import하지 않음) |
| 무역 문서 API 연결/폴더/승인 흐름 | `docs/trade-api.md`·계약 16절·`docs/plans/trade-domain-api.md` | 1~4절 구현·검증 |
| React·JavaScript·Vite / Supabase 전환 | `docs/plans/react-supabase/`·`frontend/` | 1·3~12절 구현. 콘솔 준비는 사용자 확인·로컬 Supabase URL/키 설정, 실제 계정 로그인·운영 전환 미확인. 21.1절 빌드/제공 기반 구현, 13~20·21.2절과 사람의 22절 남음. 상세 검증/제한은 PROGRESS.md |
| KE KOREA 개인 에이전트 개선 사례·선택 적용 제안 | `Team/README.md` | 참고 제안, 현재 팀 코드와 비교 후 판단 |
| 개인 에이전트 개선 사례 발표용 참고 | `Presentation/README.md` | 참고 자료, 팀 기능 구현 완료와 구분 |
| 발표 PPT | 미정 | 아직 없음 |

- 위치는 Claude가 정한 처음 값이다. 팀이 바꾸면 이 표와 README를 함께 고친다. [Claude proposal]
- 설계 결정·오류 사례·수정 이유·버전·재실행 결과는 Issue, PR('오류·재실행 기록' 칸), 팀 노션에도 남긴다.

## 9. 레포 세팅·작업 방식
마지막 갱신: 2026-11-12 · 최신 규칙 유지·PostgreSQL 시험 연결

- KE KOREA 이식 1~6절 완료에 따라 `.work/TASK.md`의 이식 전용 규칙을 삭제했다. 이식 계획과 원본 사본은 참고 이력으로 보관한다(2026-11-12, 요청자 지시).
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
- CI: `.github/workflows/rules-check.yml`. PR과 `main` 변경마다 `rules-check`(규칙 검사, 파일 지도에 없는 파일도 오류)와 `tests`(`uv sync --locked` 뒤 `uv run pytest`, PostgreSQL service 사용)가 따로 돈다. Windows worker 검사는 runner의 PostgreSQL을 시작해 사용한다. `uv.lock`이 `pyproject.toml`과 어긋나면 `tests`가 실패한다. PR에서는(본문을 고쳐도) `pr-check`도 돌아 PR 본문 '읽은 파일' 칸의 읽음 확인 코드(RULES.md·TASK.md·이 문서)와 '최신 흐름 갱신' 칸(이 문서를 안 고쳤으면 `해당 없음 — 이유`)을 본다.
