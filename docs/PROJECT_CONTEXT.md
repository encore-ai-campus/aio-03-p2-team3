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
마지막 갱신: 2026-11-19 · 수신 메일의 일정과 계약 확인

- PI·PO·PL·CI의 `최신 설정 정보 적용`은 공통 refresh-settings 경로에서 새 revision을 만들고 회사·계좌, 저장 이름이 일치하는 거래처 프로필, 최신 단가표 가격을 적용한다. 수기·확정 단가는 보존하고 기존 발급 파일은 유지한다. PI 연결 CI는 같은 PI 문서의 최신 승인 revision 거래 정보를 반영한다. 누락 입력은 팝업에서 바로 저장하며 PL 포장 행 오류도 해당 입력을 연다. 기능 검증은 별도 요청 전까지 보류한다.

- CI 시작 화면은 원문 붙여넣기·직접 작성·PI 문서 불러오기 세 선택지를 같은 카드로 제공한다. 앞의 두 방식은 PI 없이 CI를 작성하고, 원문 추출은 별도 스키마로 근거를 검증한 뒤 기존 단독 CI 가격 확인·검토 흐름에 연결한다. PI 불러오기는 본인 PI의 최신 버전과 기존 승인 규칙을 사용한다.

- PI 독립 문서 API는 같은 사용자의 PI에서 현재 또는 과거에 사용된 문서번호가 중복되면 생성·다른 번호로 수정할 때 409로 안내한다. 앞뒤 공백은 비교에서 제외하고 번호를 입력하지 않은 초안과 기존 중복 문서의 같은 번호 유지 수정은 허용한다. 직접 입력과 원문 추출이 같은 저장 검사를 거치며 기존 메일 경로·다른 사용자·다른 문서 종류는 변경하지 않는다.

- 서비스: 사용자별 Gmail 메일을 분석해 답장 후보 2~3개를 만들고, 사용자가 고른 후보만 같은 스레드로 보낸다. 거래 메일은 필수 항목이 빠지면 재질문 후보, 갖춰지면 국내 견적서 또는 PI·PO·CI·PL 초안을 만든다. 문서 확정과 메일 발송 승인은 별개다.
- 일정 문의는 기본 캘린더의 향후 30일 바쁜 시간을 읽어 요청 시간 확인, 충돌과 대안, 시간·소요 시간 보완 질문을 초안에 표시한다. 계약 문의는 메일 발신자와 연결한 계약서의 조항을 검토한다. 메일함에서 일정 상태와 문서 근거를 확인하며 실제 회신은 기존 승인 절차를 거친다.
- 현재 지원하는 실행 방식은 아래와 같다. 메일 사전 제외는 OpenAI Decisions, 기존 생성·분석은 OpenAI Responses API를 쓰며 기본 모델은 `gpt-6-luna`, 변경값은 `OPENAI_MODEL`이다(#127·#152·#159~#163).

| 실행 방식 | AI 키와 호출 위치 | Gmail 수신 |
|---|---|---|
| `server` + `stored_key` | 본인이 `/settings`에 등록한 암호화 DB 키, 서버 호출 | 공용 Google OAuth·Pub/Sub |
| `server` + `local_worker` | 연결한 본인 PC의 개인 환경 파일 키, PC 호출 | 서버가 수신·승인 발송, PC가 AI 처리 |
| `local` | PC `.env` 키, Google 연결과 독립적으로 로컬 앱 호출 | 개인 OAuth·루프백 콜백, 연결된 user_id별 순차 history 수집 |

- React `/app/agent`는 대화 요청→업무 도구 실행→추가 질문/후보 직접 선택→문서/발송 별도 승인과 결과 링크를 제공한다. 기존 마스터의 순차 tool calling과 기존 메일·문서 서비스/검증을 재사용한다. 대화·질문·승인은 PostgreSQL 체크포인트와 본인 화면 투영으로 복원하며, 재시작 후 진행 중 외부 쓰기는 자동 재생하지 않는다. 단일 앱 프로세스·사용자별 1건·요청당 최대 12회 모델 호출이다. 작업 타임라인을 펼치면 이번 실행의 현재 단계와 완료한 단계가 보인다. 기존 2초 조회로 받은 접수 시각을 기준으로 새로고침 뒤에도 경과 시간이 이어지고, 답변·승인 대기나 실행 종료 시 서버가 기록한 종료 시각에서 멈춘다. 발급한 PI·PO·CI·PL은 종류·번호·거래처·한국 발급일로 찾고, 당시 승인 버전의 파일을 타임라인에서 내려받는다. 이전 작업 결과와 상세 링크는 완료 후 타임라인에서 확인한다. 확인 카드는 승인 대기·답변 대기 배지와 메일 프레임·문서 카드(종류 색칩·다운로드 버튼)로 보여 주고, 질문은 문서 종류 선택·ID 입력 등 항목별 폼으로 답한다. 작업 결과는 발급 문서 카드·답장 후보 카드·문서함 인용 카드로, 그 외 자료는 항목별 표(key-value)로 나타내며 원시 JSON은 노출하지 않는다. 마크다운 답변은 제목 단계·인용구·표 스타일로 렌더링한다. 대화 목록 서랍과 스티키 컴포저를 쓰며 시안은 `docs/plans/agent-chat-ui/`에 있고 상세 동작은 [계약 17.4절](CONTRACT.md#174-대화형-업무-도우미-2026-11-18)에 있다.
- React `/app/inbox`는 본인 수집 메일을 상태 탭(답장 대기·확인 필요·처리 중·전체, 목록 응답의 `status_counts` 건수 표시)·검색·두 컬럼(목록/상세 각자 스크롤, 상세 머리는 스티키)으로 확인하고 실제 수신자 확인 뒤 승인 발송한다. 머리의 Gmail 연결 상태 링크는 제거했고(연결 관리는 설정 연동), 발송 확인은 모달·결과는 토스트로 알린다. 첨부 요약은 문서번호와 PDF만 보여 주고 금액은 초안 본문과 견적서 상세에서 확인한다. 목록은 30초, 처리 중 상세는 5초에 갱신하며 숨긴 탭의 조회는 쉬고 요청/타이머를 정리한다. `/api/mail/*`는 Bearer 전용이며 기존 승인 서비스를 사용한다. 국내 견적은 같은 화면에서 누락 단가를 채우고 합계/PDF를 확인하며, ready 이후 수정과 동시 변경은 거부한다. 금액·수량은 정수 문자열로 전달한다. 기존 HTML `/inbox`·`/threads/{thread_id}`와 실행 기록 링크는 유지한다. AI 답장 후보는 발송 전에 제목·본문을 직접 수정해 저장할 수 있으며, 수정 중에는 발송 버튼을 막고 서버가 현재 저장된 내용과 미리보기의 제목·본문을 비교한 뒤 승인 발송한다. 이전 버전의 미리보기로 보내려 하면 409로 중지한다. 발송했거나 다른 후보 발송으로 종료된 후보는 수정 불가다. 새 메일 초안은 업무 도우미에서 저장하며 과거 Gmail 전체 동기화는 보류다. 공개 페이지도 유지한다. 시안은 `docs/plans/mailbox-ui/`에 있다.
- React `/app/status` 작업현황은 메일(스레드별 최신 처리, 메일함과 같은 기준)·채팅 대화·무역 문서를 읽기 전용으로 합쳐 "AI가 처리한 업무·멈춘 지점·내가 할 일"을 한 화면에 보여 준다. 소스 상태를 진행 중·답변 대기·승인 대기·완료·결과 확인 필요·처리 안 함으로 정규화하고, 상태 침은 건수가 붙은 필터다. 남은 조치 버튼이 메일함 승인(`/inbox?thread=`)·채팅 답변(`/agent/{id}`)·문서 작성(`/trade/{kind}/{id}`)으로 이어지고, 메일 상세는 기존 실행 기록의 마스킹·라벨을 그대로 재사용하는 `/api/status/runs/{run_id}` 타임라인을 펼쳐 본다(2026-11-18 실행 기록 자리 탭 `/app/activity`는 이 역할과 겹쳐 제거했고 기존 HTML `/runs` 실행 기록은 유지한다). 화면을 열어도 그래프·AI를 다시 실행하지 않으며, 진행 중이 있을 때만 15초 갱신한다. 채팅 진행 중 단계·견적서(Quote) 행·독립 문서 AI 호출의 run 기록은 v1 범위 밖이다(계획 17절). 시안은 `docs/plans/status-screen/`에 있다.
- 독립 문서 API `/api/trade/{pi|po|ci|pl}`는 직접 입력/AI 추출 → 수정 → 검토 → 승인·취소 → PDF/XLSX 발급을 제공한다. 이 승인은 Gmail을 발송하지 않는다. React 로그인·설정·PI에 이어 PO·CI·PL 화면을 구현했다. CI의 PI 목록은 본인 PI마다 최신 버전 한 건만 표시한다. PI 연결 CI의 서버 생성/추출은 선택 버전 승인 후에 가능하다. PI 없이 직접 작성하는 CI는 거래 정보와 선적 정보를 입력하고 기존 판매 단가표·단가 직접 확인 규칙으로 계산해 검토·발급한다. 브라우저에서 가상 데이터로 두 경로를 확인했으며 실제 운영 연결은 확인하지 않았다. PL은 합계 승인과 최종 발급 승인을 따로 수행한다(7절·[API 안내](trade-api.md)). 문서별 `agent.py`는 구조화 추출 함수이며 독립 StateGraph나 마스터 챗봇은 아니다.
- 문서함(지식 문서) `/app/documents`·`/api/knowledge/documents`는 PDF/DOCX/XLSX/TXT/PNG/JPEG 업로드 → 전량 비전 전사 → 의심 원문 대조/수정·확정 → 조항 parent-child → 자식 임베딩/pgvector 저장을 제공한다. 원본은 기존 private Storage, 본문·부모·벡터는 기존 PostgreSQL이며 두 모델은 독립 주입/설정이다. 본인만 조회/처리하고 재처리 실패는 이전 성공 인덱스를 보존한다. 업무 도우미는 파일명으로 본인의 업로드 파일을 찾아 원본 링크를 안내하고, 내용 질문에는 게시된 조항 원문과 페이지 출처를 반환한다(계약 17.4·18절). 지식 문서 메뉴는 문서함으로 통합했고 `/app/knowledge`는 선택 문서 query/hash를 보존해 이동한다. 업로드 목록·원본 보기(기존 페이지 렌더러·전체 페이지 수 헤더·이전/다음 탐색)·다운로드는 추출 실패 때도 사용할 수 있다.
- React 문서함은 탭 2개(생성된 문서·업로드된 문서)로 메타데이터 목록을 보여 준다(2026-11-18 개편). 생성된 문서 탭은 무역 4종 목록 API(`/api/trade/{pi|po|ci|pl}`)를 프런트에서 병렬 조합하며 `DocumentSummary`에 거래처(PI·CI·PL은 buyer, PO는 seller)와 등록일을 더했다. 행 클릭은 기존 `/app/trade/{kind}/{id}` 문서 화면으로 간다. 업로드된 문서 탭은 탭 줄 오른쪽 '문서 업로드' 버튼 하나로 올리고(형식·제약 안내는 버튼 결과 줄에) 형식·상태 알약·크기·날짜 목록표를 쓰며, 행 클릭 시 목록을 대체하는 원문 대조·확정 화면으로 들어간다 뒤로 가기로 목록에 돌아온다(대조·확정 플로우 무변경, 수동 새로고침 없음). 도메인 간 aggregation API는 만들지 않았다. 계획: `docs/plans/documents-ui/documents-v2.md`.
- 채팅 결과에 새 메일 초안 편집, 기존 답장 변경 전후 승인, 미완성 무역서류와 이어 쓰기, 원본 메일 첨부 다운로드, 회신 대기 알림이 표시된다. 기한이 지난 후속 알림은 앱 상단에 표시되며 받은 메일의 알림 관리에서 확인·취소한다.
- 채팅의 등록 단가 카드는 품목명·SKU·통화·단위·가격 기준과 적용 대상을 표시한다. 거래처 카드에는 본인 설정의 등록 이름과 연락처를 표시한다.
- 채팅의 메일 검색 카드는 검색 위치·기간·답장 조건과 매칭된 본문 미리보기, 발신자, 받은 시각, 원문 링크를 표시한다. 앱에 수집된 발송 이력의 범위를 안내한다.
- 업무 채팅의 `AssistantMarkdown`은 모델 답변의 일반 Markdown과 GFM 표를 렌더링한다. 답변 전체를 감싼 `md`·`markdown` 펜스는 문서로 펼치고, 코드 예제는 복사 가능한 코드 블록으로 유지한다. 표·코드는 내부에서 스크롤하고 원시 HTML과 외부 이미지를 로드하지 않는다. 후속 결과 카드의 표시 규약은 `docs/plans/chat-workflows.md` 1절에 있다.
- React `/app/calendar` 일정 탭은 본인 주 캘린더 일정을 읽기 전용으로 월간 격자+선택 날짜 목록(종일 먼저·시작 순)으로 보여 준다. `GET /api/calendar/events`(Bearer, offset 포함 ISO start·end, 범위 ≤62일)가 일정 시각을 Google 원문 표기로 돌려주고 화면이 현지 시간대로 날짜 칸을 나눈다(종일 end는 배타적으로 계산). 같은 달은 캐시로 먼저 보여 주고 새로고침·월 이동 때 다시 받으며, 자정 넘김·여러 날 종일도 하루씩 펼친다. 미연결 사용자에게는 설정 연동 카드로 안내한다. 일정 등록·변경·취소는 업무 도우미 대화의 승인 카드를 쓴다.
- 메일 그래프는 `make_quote` → `create_trade_document`로 네 무역 문서 초안을 저장한다. 새 React 메일 API/화면은 quote/trade 후보의 관련 문서·상태·revision을 전달하며 기존 검토 화면으로 연결한다. 최종 메일 발송은 기존 가격/직인/PL 합계/CI 근거·후보 claim 검사를 유지하고 오래된 무역 revision은 거부한다. legacy HTML의 trade 링크 누락은 그대로이며 새로운 메일함은 React 경로를 사용한다. 실제 무역 메일 화면 완주/운영 확인은 별도로 남는다.
- 과제 R-01·R-02·R-09·R-10의 기존 실행 근거는 Gmail 수신 경로이며, 현재 코드는 업무별 마스터 StateGraph에서 호환 준비 단계를 실행한다. 독립 문서 작성/추출 API는 그 그래프를 실행하지 않으므로 PI 폼 완주만으로 성찰·기억·도구 선택을 시연했다고 볼 수 없다. 마스터 챗봇·멀티 에이전트는 과제 필수 조건이 아니다. 대표 흐름과 실제 배포 검증의 차이는 [서비스 연결 검토](plans/react-supabase/PROGRESS.md#서비스-연결-검토2026-11-13)를 참고한다.
- Google 로그인·암호화 토큰 저장·감시 갱신과 푸시 수신은 구현됐다(#79·#81). 로컬 Gmail 수집은 Pub/Sub·watch/stop 없이 동작한다(#160). 실제 운영 연동의 확인 범위는 6·7절과 #157에서 구분한다.
- 남은 범위: 필수 항목 출처는 현재 `app/quote/required_fields.py`의 `source="config"`, `evidence=[]`다. 규칙 근거 RAG는 gmail-quote-mvp 22절의 후속 작업이며, 일정 도구 후보는 `.work/design/api-choice.md`의 '일정 도구 추천 후보'에 있다. 빈 시간 조회는 바쁜 구간을 사용하고, 업무 도우미의 일정 목록 조회는 제목과 시각을 읽는다(4절).
- 상세 위치: [공통 계약](CONTRACT.md) 6·9·10·15·16절, [독립 문서 API](trade-api.md), [로컬 실행 계획](plans/local-openai-execution.md) 1~5절. 계획 머리말과 README 일부의 '미구현' 표현은 작성 당시 기록이며, 현재 지원 범위는 위 표처럼 코드와 병합된 구현 PR을 대조했다.

## 3. 그래프 상태·기억 (공통 부분)
마지막 갱신: 2026-11-18 · 대화형 마스터 도구·저장·API·React 연결·무역 문서 설정 갱신

- 대화형 상태는 messages/agent_calls/turn/tool_call/dialog_question을 더한다. 사용자 요청 회차별 최대 12번 판단하고 실제 결과를 기록한다. 인증 주입과 실행 승인 권한은 체크포인트와 분리한다.
- 범용 상태는 `app/graph/master/state.py`의 `WorkflowState`, 입출력은 `app/graph/schemas.py`다. 작업 DAG·실제 결과·최신 회차 근거·질문/승인 제안·실행 시도/영수증을 분리한다. 마스터는 순차 실행하고 map을 task/action ID로 교체한다. 외부 효과는 성공/실패/불명으로 구분하며 승인 권한은 체크포인트에 저장하지 않는다. 상세: 계약 2.1·3.0·17절.
- 정의 원본: `app/graph/state.py`의 `AgentState`·`initial_state`, [공통 계약](CONTRACT.md) 2·3.4·7·12.4절. 입력(`run_id`·`user_id`·`email`), 기억(`thread_context`·`long_term`), 판단(`intent`·`selected_tool`), 거래·결과(`deal_terms`·`required_fields`·`missing_fields`·`candidates`·`quote_draft`·`trade_doc_draft`), 성찰·오류·횟수·종료 상태를 분리한다.
- `deal_terms`는 국내 `DealTerms`와 무역 `TradeDocTerms`를 `doc_kind`로 구분한다(없으면 `quote`). 무역 수량·금액은 Decimal 문자열이다. 정확한 필드·기본값은 코드와 계약 2·15.2절에 있다(#107·#112).
- `tools_called`·`reflection_history`·`errors`·`call_retries`는 누적 리듀서다. 통신·형식 재시도(`call_retries`)와 성찰 재실행(`reflection_retries`·`reflection_retries_by_type`)은 따로 센다. `notice`에는 사용자 키와 개인 PC 실행 오류 안내도 있다(#91·#152·#162).
- 기억 구현: `app/services/memory.py`가 본인·같은 스레드의 요약/미요약 원문과, 본인 회사·단가·선호 및 같은 상대의 최근 거래 5건을 읽는다. 현재 메일 조건이 우선하며 과거 수량·단가·납기를 이번 거래로 복사하지 않는다. 다른 사용자·상대방의 기억과 미래 메일은 제외한다(#88).
- 긴 스레드는 현재 메일 포함 8개 또는 본문 12,000자를 넘을 때 최근 원문 4개를 남겨 누적 요약한다. 원문은 DB에 보존하고 성공한 요약만 커서를 갱신한다. AI 대기는 DB 트랜잭션 밖에서 수행하며, 대기 중 요약/커서가 바뀌었으면 덮어쓰지 않는다(#162).
- 원문·확인 조건·직전 결과는 `save_pending`에서 저장한다. 장기 거래/문체 기억은 본인 승인·발송 성공 뒤 실제 수신자를 기준으로 저장한다. 기억 저장만 실패하면 발송 성공을 유지하고 자동 재발송하지 않는다.

## 4. 도구(API 연동) (공통 부분: 도구 스키마)
마지막 갱신: 2026-11-19 · 수신 일정 조회와 한영 계약 검색

- 업무 노드의 SQL/HTTP 경계는 `app/graph/mail/adapters.py`·`documents/adapters.py`·`calendar/adapters.py`다. 기존 서비스/문서 정책을 재사용한다. 발급의 실제 file_ids를 다음 메일에 연결하며 Storage bytes 해시와 MIME 첨부 일치를 검증한다. 원래 후보 claim·발송 1회 규칙을 유지한다. 일정은 설정에서 연결한 `calendar_tokens`를 `ExistingCalendar`가 실제 Google Calendar로 연결하며 `app/main.py`의 `agent_runtime`이 주입한다(미연결은 `calendar_not_connected`). 호출기 `CalendarClient`는 freebusy 조회·일정 등록·등록 확인 호출과 `check_calendars` 공용 오류 체계를 갖췄고, 등록 거부(400·409)는 `calendar_rejected` 확정 실패다(#245). 일정 탭과 채팅이 공유하는 읽기 전용 `list_events`(기간 내 일정 목록, 페이지네이션 상한 초과는 잘린 목록 대신 실패)는 `app/services/calendar.py`를 통해 `GET /api/calendar/events`와 채팅이 쓰며 토큰 갱신·실패 분류는 `calendar_access_token` 헬퍼와 연결 상태 조회 체계를 재사용한다(미연결 409·범위 검증 400). 등록은 결정적 이벤트 ID와 `calendar_event_receipts` 영수증으로 멱등을 지키고 타임아웃·5xx는 `unknown` 뒤 조회로 복구한다. 새 자연어 planner/repair는 기존 사용자 AI 호출 경계를 쓰며 PC v1에 없는 스키마는 서버 키 대체 없이 실패한다. 명시적 Plan은 planner를 호출하지 않는다. 상세: 계약 17절.
- 대화형 업무 도구는 `master/tools.py`의 27개 @tool이며 기존 사용자 키 Responses 모델에 바인딩한다. 문서 입력 스키마/기존 input을 조회해 보완하고 모델의 단가 강제 변경 승인은 막는다. 발송 후보는 사용자가 직접 선택한다. `search_trade_documents`는 본인의 승인 기록과 발급 파일로 범위를 제한하고 최근 10건의 링크를 반환한다. `search_knowledge_documents`는 기존 임베더와 pgvector에서 검색한 조항을 파일명·페이지 근거와 함께 반환한다. `list_calendar_events`는 본인 주 캘린더의 제목과 시각을 읽으며 최대 30건과 전체 건수를 반환한다. `find_slots`는 지정한 캘린더의 빈 시간 후보를 찾고 `create_event`는 사용자가 고른 시간만 등록 제안한다.
- `search_mail`은 본인 앱에 수집된 수신 메일의 제목·발신자·본문, 수신 기간과 실제 답장 발송 여부로 검색한다. 받은 시각 이후 같은 스레드의 앱 발송 기록을 사용하며 초안은 발송으로 세지 않는다. 조건에 맞는 수신 메일을 스레드별로 묶고 최대 10건과 다음 커서를 반환한다. 기존 메일함의 검색 계약은 유지한다.
- `search_trade_prices`와 `search_counterparties`는 본인 무역 설정의 등록 행을 읽는다. 거래처 이름·별칭을 대조하고 SKU가 알려졌으면 정확한 코드를 먼저 사용한다. 거래처 단가와 공통 단가를 표시하며 동명 후보와 미등록 결과를 구별한다.
- `prepare_move_calendar_event`와 `prepare_cancel_calendar_event`는 이번 요청의 기본 캘린더 목록에서 확인한 일정만 제안한다. 반복 일정은 선택한 회차만 적용한다. 승인 전후의 버전·시간 충돌을 확인하고 Google에 버전 조건을 보내며, 타임아웃 뒤에는 같은 일정 상태만 조회한다. 읽기 권한만 있는 연결은 설정에서 쓰기 권한을 추가할 수 있다.
- 공통 AI 진입점은 `app/llm/client.py`의 `call_structured()`와 `app/services/openai_keys.py`의 `user_openai()`다. 메일·요약·성찰과 네 문서 추출이 같은 OpenAI 모델/구조화 출력을 쓴다. `stored_key`는 Fernet으로 암호화한 본인의 OpenAI 키를 읽고, `local`은 전용 루프백 프로세스의 환경 키, `local_worker`는 지정 소유자의 개인 파일 키를 사용한다. 키 누락·복호화 실패·PC 오류 때 다른 사용자/서버 환경 키로 대체하지 않는다(#127·#152·#159·#162).
- 수신 전 `app/llm/mail_gate.py`는 같은 본인 키로 Decisions `gpt-6-luna`의 exclude/keep 한 질문을 호출한다. 명확한 무관 + confidence ≥ 0.95만 제외하고 애매함/회사 업무는 기존 그래프에 전달한다. 오류는 원문 보존 후 needs_review, local_worker는 미지원이다. no-reply/프로모션/소셜만으로 제외하지 않는다. 생성/분석 프롬프트는 기존 분기를 유지하며 analyze_email.v2로 회사 업무 전반을 다룬다.
- 지식 문서 `DocumentExtractor`/`Embedder`는 위 구조화 호출로 가장하지 않고 OpenAI Responses 시각 입력/Embeddings API를 각각 감싼다. `UserKeyAccess`의 본인/실행 모드 검증은 재사용하며 미지원 local_worker·키 누락은 공용 키 대체 없이 실패한다. 비전 기본값은 현재 OpenAI 모델, 임베딩은 사용자 선택 text-embedding-3-small/1536이며 KNOWLEDGE_*로 따로 바꾼다. 비전 store=False·요청당 180초·SDK 재시도 최대 3회(최초 포함 4번), 임베딩은 기존 30초·재시도 0회이며 진행 시도 프로필 고정과 명시적 재처리를 적용한다. 업무 도우미의 내용 검색은 현재 호환 임베딩 프로필의 게시본을 읽는다.
- `app/llm/`은 AI 구조화 실행·재시도·PC 위임, `app/clients/gmail.py`는 Google OAuth/Gmail 통신으로 구현이 겹치지 않아 분리 유지한다. 상세 비교와 호출 관계는 [도메인 구조도](domain-layout.md).
- 구조화 AI 호출 예산: SDK 자동 재시도 0, 호출 제한 20초. 429는 재시도 없이 한도 안내, 통신/5xx는 최대 3회(1·2초 대기), 형식 오류는 별도 1회 재시도다. PC 방식의 재시도는 서버 `app/worker/adapter.py` 한 곳에서 기존 예산과 전체 120초 기한으로 관리한다. 짧은 HTTP/예외 코드는 실행 기록에 남기고 키·원문은 남기지 않는다(#98).
- 채팅의 메일 도구는 새 스레드 초안을 앱에 저장하거나 기존 답장 후보의 변경을 승인받는다. 원본 첨부는 소유한 메시지의 Gmail 메타데이터만 모델에 제공한다. 후속 알림은 수집된 발송 메일을 기준으로 등록·목록·취소를 제공하고, 미완성 문서 검색은 현재 버전의 실제 발급 기록과 누락 항목을 대조한다.
- 메일과 채팅은 공통 `knowledge/retrieval.py`에서 한국어와 영어로 질의를 검색한다. PostgreSQL 키워드와 pgvector 순위를 합치고 모델이 질문에 관련된 실제 후보 조항을 다시 고른다. 문서함 상세에서 계약 거래처를 연결한다. 등록 주소가 일치하면 해당 연결 계약만 조회하며, 연결 문서가 없거나 같은 이메일이 여러 거래처에 등록되면 넓혀 검색하지 않는다. 미등록 주소는 본인 전체 게시 문서를 검색하고 근거 링크는 메일함 내부 검토에 사용한다.
- 등록 도구 7개: `draft_replies`, `extract_deal_terms`, `check_required_fields`, `draft_followup_replies`, `create_quote`, `create_trade_document`, `send_email`(`app/tools/registry.py`). 필수 항목은 `get_required_fields()` 한 곳에서 받고, 답장 후보는 금액·문서번호를 복사하지 않고 첨부 문서를 안내한다. `send_email`은 승인 경로에서만 호출한다. 프롬프트 버전 원본은 `app/prompts/VERSIONS.md`다.
- 무역 품목 후보: PI·PO·단독 CI·PL의 직접 입력/추출 후 품목 편집에서 `/api/trade/settings/products/search`가 본인 등록 단가표의 부분 이름·영문 오타·대표 한글 표기를 검색한다. SUPERLIGHT2/슈퍼라이트/수퍼라이트와 띄어쓰기·색상·Compact 표기를 지원하며 숫자는 정확히 비교한다. 한글 발음은 `product_search.SEARCH_TERMS` 사전 범위이고 임의 외국 상품의 자동 음역은 아니다. 최대 20개/전체 건수와 재검색 안내를 표시하며 사용자가 선택한 행의 정식 이름·코드·규격만 바꾸고 수량·입력 단가를 보존한다. 가격 확인은 해제해 기존 저장/검토에서 단가를 다시 검증한다. 검색 실패·후보 없음은 입력을 유지하고 재시도/직접 수정을 제공한다. 시연 XLSX 자체는 자동 등록하지 않으며 설정 단가표에 등록한 품목이 검색 대상이다. Gmail/국내 견적·PI 연결 CI의 원본 품목 변경은 이 기능의 범위가 아니다.
- 국내 견적: 합의 단가 → 이름·단위가 같은 단가표 → 사용자 입력 순서로 채운다. 누락 단가는 `needs_price`, 완료는 `ready`이며 정수 금액·부가세 10% 버림·30일 유효기간과 한글 PDF를 지원한다. 코드 `app/quote/`, `app/quote/router.py`; 상세는 계약 4·9·12.2절(#89).
- 무역 문서: `app/trade/{pi,po,ci,pl}/`가 도메인 업무를, `common/`·`review/`·`settings/`가 공유 계산/출력·검토·설정을 담당한다. 직접/AI 입력은 같은 계산·검증을 거친다. CI는 승인된 PI의 특정 버전·거래 사실을 보존하고 PL은 원본/계산 합계의 별도 승인을 요구한다. 검토는 문서 revision·내용 해시·회사/계좌/이미지를 고정한 뒤 승인 파일을 저장한다. 루트 호환 입구는 제거됐다(#107·#112·#114). 상세: 계약 15·16절, [API 안내](trade-api.md).
- Gmail 문서 발송은 `app/services/approval.py`의 `send_approved_quote()`·`send_approved_trade_document()`가 담당한다. 무역 문서는 `ready`·PL 합계 승인·CI PI 원문 근거·직인을 확인하고, 발송 중 문서 변경과 중복 승인을 막는다. 성공 때 문서·후보·메일을 발송 상태로 바꾸고 같은 메일의 다른 후보는 종료한다. 발송 자체는 자동 재시도하지 않으며 시간 초과/5xx는 보낸편지함 확인 후 명시적 재승인 대상이다(#85·#107).
- 개인 PC 실행: `app/worker/{protocol,service,adapter,pc}.py`가 설치된 구조화 정의·모델·소유자·장치·시도/기한을 검증한다. 서버는 키를 받지 않고 큐 결과를 암호화해 전달 후 소비/해제/기한에 지운다. 미완료/거부된 PC 결과로 후보·문서를 저장하지 않으며 만료된 임대는 자동 재배포하지 않는다. 장치 API는 메일 승인·발송·파일 권한을 갖지 않는다(#161·#162). Windows 자격증명은 `credentials.py`의 현재 사용자 DPAPI·보호 DACL, macOS/Linux는 소유자·600 권한으로 보호한다(#163). 상세: 계약 6절.

## 5. 그래프 노드·흐름 (공통 부분)
마지막 갱신: 2026-11-19 · 수신 초안 전에 일정·계약 근거 조회

- 대화형 마스터는 `plan`에서 업무 도구를 하나 선택하고 기존 prepare/승인/execute 결과를 ToolMessage로 되돌려 다음 행동을 고른다. 읽은 자료는 지시가 아니며 모델이 키/소유자/승인을 지정하지 못한다. 자연어 질문과 승인 interrupt, revision/claim·영수증 경계는 유지한다.
- 범용 진입점은 `run.Workflow`의 start/inspect/resume/recover, 조립은 `wiring.make_workflow`다. `build.py`의 StateGraph가 계획 검증 → 의존 작업 선택 → 업무 prepare → 질문/성찰/승인 → 현재 대상 재검사 → 실행 직전 체크포인트 → 실행/영수증 조회 → 실제 결과 종합을 담당한다. 메일/문서/일정 폴더의 nodes는 업무를, adapters/ports는 외부 연결을 소유한다.
- 새 질문/승인은 interrupt로 대기하고 소유자·action/hash를 검증한다. 수정은 새 준비/승인, 취소는 해당 작업과 의존 작업만 종료한다. 응답 유실/재생은 자동 발송/등록 없이 같은 영수증만 조회한다. 대화형 API는 공식 PostgresSaver를 주입해 재시작 뒤 대기를 보존한다. InMemorySaver는 테스트/기존 수신 호환 경계에만 사용한다. 캘린더 변경·취소는 승인 직전에 일정 버전과 충돌을 다시 읽으며, 영수증 복구는 Google 쓰기를 재실행하지 않는다. 계약 3.0·17절에 입출력·전이·정상/실패 시나리오가 있다.
- `start_run()`·`build_graph()`는 기존 Gmail 수신/평가/PC 경계를 유지하며 새 마스터의 수신 준비 작업으로 변환한다. 10개 준비 단계의 기존 호출/기록은 `master/inbound.py`가 연결하며 별도 StateGraph를 만들지 않는다. 본문은 `master/`, `mail/`, `documents/`로 이동했고 `nodes/`에는 PC 공개 스키마 재수출 두 개만 남는다. 기존 수신 준비 흐름은 다음과 같다.
  - `load_memory` → `analyze_email` → 일반 `draft_replies` / 거래 `extract_deal` → `check_required` → 누락 `draft_followup` / 충족 `make_quote` → `draft_replies`.
  - 후보 생성 뒤 성찰을 켰으면 `reflect`에서 필요 노드를 재실행·재검증하고, 마지막에 `save_pending`으로 저장한다. 처리 제외는 즉시 끝나며 실패는 `finish_failed`로 간다. 기존 Gmail UI의 승인/메일 발송은 기존 서비스 경로를 유지한다. 새 범용 마스터는 같은 서비스를 승인 검증 뒤 호출한다.
- 앱의 Gmail 푸시·로컬 수집·수동 처리와 채팅 초안 요청은 일정 및 문서 조회를 구성한 공통 수신 Graph를 사용한다. 초기 메일 분류 안에서 받은 시각을 기준으로 날짜·시각을 해석하고, 초안 경로를 실행하기 전에 캘린더와 문서함을 읽는다. 단독 일정 문의는 조회 상태와 확인된 시각으로 후보를 만든다. 거래처 범위 계약 조항은 기존 답장 맥락에 추가하고 순수 계약 문의를 신규 견적으로 보내지 않는다. 미등록 발신자의 문서는 메일함 검토 근거로 제시하고 답장에는 확인 안내를 쓴다.
- `make_quote`는 `doc_kind`로 국내/무역 생성 도구를 고르고 본인 회사·계좌·단가 설정과 실행 ID를 문서/후보에 연결한다. 일반·거래·재질문·견적과 무역 경로 모두 구현돼 있다(#89·#107). 결과는 `awaiting_approval`·`followup_question`·`ignored`·`failed`로 구분한다.
- 성찰은 규칙으로 환각·도구 선택 오류·필수값 누락·응답 불일치를 찾고, 문제가 있을 때만 `reflect_fix`를 호출한다. 유형별 한도는 환각 2·도구 1·누락 1·불일치 2, 전체 3회다. 한도 초과·성찰 자체 오류는 확인 필요 후보로 끝낸다(#91). 새 사용자 기본값 → 사용자 설정 → 실행 옵션 순으로 성찰 여부를 정한다.
- 직접 AI 호출의 한도 오류는 자동 재시도 없이 기본 후보 1개·`needs_review`·`rate_limit` 안내로 저장하고, 통신/형식 오류는 호출 예산 소진 후 실패한다(`master/common.py`). PC 실패는 `save_pending`의 완료 확인과 `start_run`의 안전한 오류 안내로 후보 저장을 막는다(#162).
- Gmail 수신은 `app/services/gmail_push.py`의 사용자별 직렬화·메일 유일 제약으로 중복을 막고, 해당 수집의 모든 Gmail 조회가 성공한 뒤에만 history를 갱신한다. 프로세스 내 `BackgroundTasks` 방식이며 새 triage 미완료는 DB에서 복구하고 저장된 후보는 재사용한다. 그래프 실행 중 중단은 자동 재실행 없이 확인 필요로 남긴다. 분류 실패는 원문 보존 후 커서를 진행하며 Gmail 조회 실패는 커서를 보존한다. 단, 기록 뒤 삭제되어 메시지 조회가 404인 경우 해당 메일만 건너뛰고 뒤의 메일을 계속 수집한다. 다중 수집 프로세스·공용 history 만료의 전체 재처리는 구현 범위 밖이다. 로컬 history 만료는 전체 재처리 대신 재로그인을 안내한다(#160).
- `app/runlog/`가 노드·전이·도구·성찰·오류/재시도·소요 시간을 기록한다. `/runs`·`/runs/{run_id}`·`/export`는 본인 기록만 개인정보를 가려 제공한다. 실행 종료 이유와 승인 뒤 발송 상태는 구분한다. 상세: 계약 8절, `app/runlog/router.py`.

## 6. 시험·평가
마지막 갱신: 2026-11-19 · 수신 일정·계약 근거 시험, LLM 카탈로그 선별 40회 실측·기능별 모델 프로필 수동 상향 구현·카탈로그 후보 계약(초안)

- 전체 Python 1,223건 통과·2건 건너뜀, 프런트 24건·lint·build·공개 환경 검사, 저장소 규칙 검사 경고 0개를 확인했다.
- 수신 일정과 계약의 통합 시험은 `tests/test_inbound_context.py`에 있다. 가상 Gmail 수신과 실제 임시 PostgreSQL에서 30일 조회, 시간·소요 시간 구분, 겹치는 시간 대안, 거래처·사용자 경계와 미등록 발신자의 문서함 근거를 검증한다. 실제 모델과 임베딩에 합성 메일 5건과 가상 계약서 두 건을 사용했다. 15:30 충돌 대안 두 개, 내일모레 21:00의 소요 시간 질문, 일정 미정 질문, 등록 발신자의 영문 14일 조항, 미등록 발신자의 내부 검토 근거를 확인했다. 캘린더는 대역을 사용했다.
- 업무 채팅 4~9절은 전체 Python 1,211건 통과·2건 건너뜀, 프런트 24건·lint·build·공개 환경 검사, 저장소 규칙 검사 경고 0개를 확인했다. 390px Chromium에서 변경·취소, 편집 저장 후 재접속, 실제 다운로드, 후속 알림의 등록·표시·취소를 확인했다. 합성 채팅 요청 10건에는 실제 모델과 가짜 Google을 사용했다.

- 등록한 가상 거래처 8곳의 합성 요청을 실제 수신 LangGraph와 모델에 통과시켰다. 일정·반품 계약·기존 PO 개정·첨부 대조·미회신 후속에서 필요한 도구 호출이 없었고, PI 필수 정보 요청과 광고 무시는 동작했다. 진입 조건과 결과는 [수신 메일 검증 기록](test-records/20261119_inbound_company_audit.md)에 있다.

- 대화형 마스터: 실제 StateGraph/PostgresSaver·임시 PostgreSQL·가짜 모델/Google/Storage의 관련 회귀 **85 passed**(42.55초), 프론트 lint·test 12개·build와 규칙 검사 경고 0개를 확인했다. 실제 SDK의 본인 키/도구 바인딩 모의 HTTP, API의 재시작/질문/후보 선택/승인·소유권/중복 차단, Chromium 1440/390px의 메일 발송·PI 발급/PDF·후속 대화/새로고침을 검증했다. 운영/실제 모델 판단 품질과 구분하며 상세는 [검증 기록](test-records/20261118_master_agent.md)에 있다.

- 회사 메일함: 최신 main `4a833a3` 통합 전체 Python **1132 passed·2 skipped**, 프론트 lint/test(12개)/build/환경 검사와 제출 파일 규칙 검사(경고 0개)를 통과했다. 새 수집/제외/복구·Bearer 소유권·실제 Reply-To 확인·기존 승인 발송, Chromium 1440/390px와 키보드 확인창 이동을 자동 검사했다. 실제 Decisions 합성 9건은 업무/애매함 6건 보존·광고 1건 제외·개인/취미 2건 통과이며 운영 정확도 보장이 아니다. 실제 Gmail 프로필/시험 발송에 이어 다른 계정의 가상 업무 메일 수신·Decisions keep(1.0)·기존 그래프·견적 후보 3개 생성을 확인했다. 단가 누락(needs_price) 뒤 사용자 위임으로 가상 단가를 확정하고 첫 후보의 실제 답장·PDF 첨부를 확인했다. 같은 스레드·답장 헤더·첨부 금액·승인 재전달 already_sent·실제 발송 1건을 검증했다. FOB를 국내 견적으로 선택한 기존 문서 정책과 실제 운영 확인은 제한으로 구분한다. 최종 실행 결과와 제한은 [검증 기록](test-records/20261116_mailbox.md)에 있다.

- 기존 PI 발행자 설정 갱신: 도메인/API 검사 26건, 프런트 12건·lint·build, 규칙 검사(경고 0개)를 통과했다. 전체 `uv run pytest`는 **1113 passed·3 skipped**다. 첫 전체 실행은 LibreOffice 설치 경로가 PATH에 없어 문서 변환 6건과 Windows 서버 종료 1건이 실패/오류였으며, PATH를 추가해 해당 33건을 재실행한 뒤 전체 검사를 다시 실행해 통과했다. 승인 전/후 설정 변경·새 revision·가격/거래 사실 보존·이전 발급 파일 bytes·오래된 revision/타 사용자 차단을 확인했다.

- 모델 교체 전 측정: `app/evaluation/model_benchmark.py`의 기본 dry run은 API/키 없이 호출 계획만 만든다. 개인 PC의 명시적 `--live`에서 입력 사전 계수·Standard 비용 예약·캐시/출력/추론 usage·지연·미완료 이유와 거래 정답/허용 카탈로그 ID를 검사한다. 실제 오류 원문/정답·카탈로그/혼용 질의·PNG/JPEG를 별도로 넣을 수 있다. 이미지 전사는 원본 대조 전 정확도를 통과 처리하지 않는다. 사용량 미상 오류는 예약액을 유지하고 중단하며 보고서를 덮어쓰지 않는다. 기능 단독 호출 측정이므로 메일 전체·페이지/임베딩/재시도 포함 업무 1회 총비용으로 표현하지 않는다. 운영 모델/기한/PC 출력은 유지했다. 첨부 6회(거래 Luna medium 2·Sol medium 2, 이미지 Luna medium 1·Terra low 1)를 확인했고 usage 추계 합계는 USD 0.0169561이다. Luna 거래는 형식 실패, Sol 2차는 검사 품목 필드 일치/연속 인용 과잉 차단으로 원래 실패를 보존한다. 이미지 최초 통과는 Luna 추측 실패/Terra 가림 표시·미확인으로 정정됐다. 실제 청구·업무 총비용·카탈로그/대표 반복·실제 마스킹 UI/품목별 강제·침묵 추측 차단은 미검증이다. 모델 자기 신고와 독립된 서버 확인 계약과 복구 절차는 인계 검토(개인 PC 보관, 공개 레포 제외), 후속 단계는 [측정 계획](plans/llm-quality-and-cost.md)에 있다. 추가 PC 비교 ZIP에서 측정기만 수정/다른 세 파일 원격 동일을 확인해 PC 진단을 그대로 복구하고 진단 회귀를 추가했다. 관련 pytest 27개 통과. 이전 Codex만의 미커밋 소스는 미복구다. 복구/저장 응답 검토 스크립트는 API/키 없이 기존 자료를 재사용하고 응답 미저장은 미확인으로 남긴다. 합성 원문의 비고 연결 과잉 차단은 재현했으나 이후 PC 재검사 첨부에서 Sol 2차 저장 결과의 품목 필드 일치/자동 실패 유지를 확인했다. 재검사 충돌 누적을 독립 오류로 세지 않으며 이미지 두 저장 결과도 기존 사람 정정을 우선한다. 카탈로그 시험 파일은 0개여서 읽기 전용 수집 도구로 실제 ID/이름/규격을 확보하는 단계다. 수집 도구의 모의/설정 검사 5개는 통과했으나 실제 DB 통합 3개는 환경의 소켓 생성 차단으로 미검증이다. 수집은 앱 인증/서버 소유권 검증 통과를 의미하지 않는다. PC에는 DB 환경파일이 없고 Render에만 설정됐음을 확인했다. 임시 DB 주소 입력 뒤 OperationalError로 수집은 실패했으며 실제 카탈로그는 미확보다. 진단 v2는 저장 이메일을 재사용하고 실패 단계/고정 원인 코드만 내보낸다. 진단 포함 단위 18개 통과, 실제 DB 통합 3개 미검증을 유지한다. v2 PC 결과는 Render 내부 호스트의 DNS 해석 실패(database_connect)로 확인됐으며, 같은 DB의 External URL을 PC 임시 입력에 사용해 이어서 확인한다. 운영 Environment는 변경하지 않는다. 이후 외부 주소로 DB 연결과 읽기 전용 조회·입력 이메일의 유일 계정 매칭은 통과했으나 해당 계정 sale 카탈로그는 0개(owned_catalog_empty)였다. 구매 역할/전체 사용자 데이터 부재로 확대 해석하지 않으며 앱 설정의 동일 계정·판매/구매 단가 저장 여부를 먼저 확인한다. 이후 사용자가 별도로 확인한 팀원 KE KOREA Supabase는 Session pooler 형태/5432로 접속을 시도했으나 connection_timeout이다. Render sale 0개 결과를 이 Supabase의 데이터 부재로 해석하지 않는다. PC TCP True 뒤 TLS/연결 20초에서도 Supabase 연결 시간 초과가 발생했다. 인증·앱 스키마·실제 카탈로그는 미확인이다. 외부 접속 반복을 멈추고 로그인된 Supabase SQL Editor의 public 테이블/열 메타데이터 읽기 전용 확인으로 준비 경로를 전환했다. 사용자 목록에서 aio3_catalog_products(sku)/aio3_catalog_members를 확인했으나 행수·회원 매핑/권한은 미확인이다. fetch-only로 확인한 main 3678e05도 개인 price_list_items 검색을 유지한다. 기존 변경을 병합/덮어쓰지 않고 공유 테이블 메타데이터에서 상품 49·회원 3, SKU PK와 members.user_id→auth.users UUID FK, reader/RLS 읽기 정책을 확인했다. 관리자 SQL Editor에서도 본인 이메일 유일 매칭+reader 회원 조건을 적용한 가격/별칭 제외 export를 준비했다. 이후 지정 이메일의 유일 계정+reader 회원 조건을 통과한 SKU 49개를 가격/별칭 없이 수신했다. 관리자 SQL의 이메일 선택이므로 앱 인증/현재 서버 재검증과는 구분한다. 실제 SKU 정답 초안 10개와 Luna medium/Sol medium의 무료 호출 계획 20개를 준비했으며 사용자가 정답 10개를 모두 확인했고 별도 확인본/해시 결합 승인 기록을 보존했다. 준비 관련 검사 7개 통과, 추가 모델 호출은 0회다. 기존 측정기·준비 함수를 재사용하는 PC 최소 선별 실행기 `scripts/run_shared_catalog_live.py`를 준비했다. 기본은 API 미호출 계획 출력이고 `--live`에서만 호출한다. 키는 비공개 입력창으로만 받으며 Luna/Sol medium x 10질의 x 1회(20회)를 90초/출력 2048로 실행한다. 생성 전 전체 요청을 계수해 최악 예약액을 예산과 대조하고, 상태 파일로 기존 결과를 재사용·checkpoint하며, 시간 초과/usage 미상은 예약액을 유지한 채 중단해 다른 모델을 자동 호출하지 않는다. 키 취소·시작 미확인은 진행을 지우지 않는다. 가짜 클라이언트 테스트를 통과한 뒤 PC에서 20회를 실행했다. PC에서 Luna medium 3회 반복(30회)과 Sol medium 1회(10회), 총 40회를 실행했다. 40회 모두 완료됐고 시간 초과·미완료·사용량 미상은 0건이며 자동 정답 대조는 Luna 30/30·Sol 10/10 통과했다. Luna 3회 반복에서 질의별 후보 집합이 모두 같았고 Sol과도 같았다. 입력은 호출당 약 4.4K토큰이며 요금표 추계는 Luna 30회 USD 0.00604·Sol 10회 USD 0.0919(Luna 첫 10회 USD 0.00468·반복 20회 USD 0.00136, 첫 회 기준 Sol이 약 20배)로 합계 USD 0.0979이고 실제 청구액과는 대조하지 않았다. 평균 호출 시간은 Luna 2.0초(최대 5.3초)·Sol 2.2초다. 질의 10개·SKU 49개의 선별이라 대규모 카탈로그·다른 브랜드/표기·서버 권한/버전 재검증·Sol 반복은 미확인이며 전체 품질 통과가 아니다. 운영 모델/Render와 프로필/후보 기능은 바꾸지 않았다. 실제 SKU·상태 파일은 공개 레포에 올리지 않는다.

- 기능별 모델 프로필(2026-11-19, 결정 1a·2a 적용, PR #256): 서버 `app/llm/profiles.py`가 [모델 프로필 계약](plans/llm-model-profiles.md)의 `llm-model-profiles.contract.json`을 읽는다. 기본은 모든 기능 baseline(현재와 같은 요청)이고, `LLM_PROFILE_DEFAULT_STRUCTURED`·`LLM_PROFILE_TRADE_EXTRACTION`에 `sol-medium`, `LLM_PROFILE_VISION_TRANSCRIPTION`에 `terra-low`를 명시했을 때만 상향한다(`manual_upgrade`: 품질 게이트 없이 오류 대응용, 재시도 0·시간 초과 뒤 재요청/다른 모델 없음). 개인 PC 경로·매핑 밖 프롬프트는 baseline, 비전은 새 처리부터. 잘못된 값은 서버 시작 오류. `llm_call` 기록에 `profile_id`·모델·노력치·`error_detail`(시간 초과/미완료/권한)·토큰 사용량이 남는다. 검사: 계약 18개·해석기/호출 15개(모의 HTTPS로 실제 SDK 요청 본문 확인, baseline 요청 동일 포함)와 관련 회귀(llm·키·로컬·PC 실행·무역 추출·지식 문서) 통과. 유료 호출 0회라 상향 모델의 실제 수락·품질·Render 적용은 미확인이다. [모델 프로필 계약](plans/llm-model-profiles.md)과 기계용 `llm-model-profiles.contract.json`이 기능 키 5개(`default_structured`·`trade_extraction`·`catalog_candidates`·`vision_transcription`·`mail_gate`)별 모델·노력치·실행 방식별 timeout/출력 상한/기한을 정하고, `scripts/check_model_profile_contract.py`가 현재 코드 baseline 값과 대조한다(테스트 17개). [카탈로그 후보 계획](plans/catalog-candidates.md)은 별칭 사전 없이 권한 범위의 실제 ID만 후보로 받고 행마다 사용자의 명시적 선택 영수증을 요구하는 서버 검증 계약이며, 시험용 기준 구현 `tests/fakes/catalog_candidates_reference.py`와 모의 시험 20개(프로필 계약 소비 2개 포함)로 고정했다. 카탈로그 후보 프로필은 `production_available: false`라 호출되지 않는다. 운영 구현은 품질 게이트·공유 카탈로그 읽기 경로 결정(카탈로그 계획 4절 1번)·계약 확정 뒤다.

- PL 모바일 계획 3절: 실제 FastAPI·임시 pgvector PostgreSQL·가짜 인증/추출/Storage와 Chromium으로 PL 직접/가짜 추출의 두 승인·취소·행 수정·미저장 차단·409 입력 보존·다운로드 재시도 해시 일치를 확인했다. PI/PO·CI 연결/단독 포함 브라우저 7개 경로와 320/390/768/1440px 배치를 검증했다. 전체 `uv run pytest` **1089 passed·2 skipped**, 규칙 검사(경고 0개)·프론트 test(11개)/lint/build/check:env를 통과했다. 실제 기기/운영 연결은 미확인이고 상세 결과는 [기존 검증 기록](test-records/20261113_po_ci_pl_screens.md#issue-210-pl-모바일-보완2026-11-17)에 둔다.

- CI 모바일 계획 2절: 실제 FastAPI·임시 pgvector PostgreSQL·가짜 인증/추출/Storage와 Chromium으로 390px PI 연결·단독 직접/원문 보완→발급/다운로드를 확인했다. 55개 PI 목록/실패 재시도·미승인 차단·별도 PI 탭 보완 뒤 명시적 재선택의 선적 입력 보존·선택 버전 가격/FOC 고정·409/재조회·다운로드 실패/재시도 해시 일치를 검증했다. 320/768/1440px 배치·크기 변경/키보드와 PI/PO 공통 배치 회귀를 포함한다. 전체 `uv run pytest` **1087 passed·2 skipped**, 규칙 검사(경고 0개)·프론트 test(11개)/lint/build/check:env를 통과했다. 실제 기기/운영 연결은 미확인이고 상세 결과는 [기존 검증 기록](test-records/20261113_po_ci_pl_screens.md#issue-209-ci-모바일-보완2026-11-17)에 둔다.

- PI/PO 모바일 계획 1절: 실제 FastAPI·임시 pgvector PostgreSQL·가짜 인증/추출/Storage와 Chromium으로 390px 직접/원문 보완·검토 취소/수정/승인·PDF/XLSX 다운로드·ID 재개를 확인했다. 320/768/1440px 배치·390→1440→390px 입력/단계/요약/포커스 보존·실제 409 입력 보존·다운로드 실패/재시도 해시 일치와 키보드 접근을 검증했다. 전체 `uv run pytest`는 **1084 passed·2 skipped**, 프론트 test(11개)/lint/build/check:env와 규칙 검사(경고 0개)를 통과했다. 실제 기기 키보드·운영 연결은 미확인이며, 수치와 공통 규칙은 [기존 검증 기록](test-records/20261113_po_ci_pl_screens.md#issue-208-pipo-모바일-보완2026-11-17)·[모바일 계획 1절](plans/trade-mobile-workspaces.md#1)에 둔다.

- 최신 main `ab01eda`와 Calendar OAuth 충돌을 합쳐 서버의 Calendar 초기화·로컬 Gmail 저장소 주입과 문서함/로컬 실행 변경을 함께 유지했다. 통합 전체 pytest는 **1082 passed·2 skipped**, 프론트 lint/test(11개)/build와 규칙 검사를 통과했다.

- Calendar OAuth는 실제 임시 PostgreSQL·가짜 Google/JWKS로 state/PKCE·갱신/해제·계정/서비스 격리·실패를 검증하고, Chromium에서 단독/동시 연결·새로고침·390px·오류 복구를 확인했다. 전체 `uv run pytest`는 **1067 passed·2 skipped**(Windows 전용), frontend lint/test(11개)/build/공개 환경 검사와 규칙 검사(경고 0개)를 통과했다. 상세 실행 결과·변환기 환경 보완과 실제 운영 미확인은 [검증 기록](test-records/20261116_calendar_oauth.md)에 둔다.

- 로컬 실행 정리: 전체 `uv run pytest` **1051 passed·2 skipped**, 규칙 검사 경고 0개, 프론트 lint/test(11개)/build/공개 환경 검사를 통과했다. 실제 임시 PostgreSQL과 가짜 Google/OpenAI/Storage로 Gmail 미연결 Supabase 사용자 2명의 문서 저장·소유권 분리, 키/리스너 누락의 저장 전 차단, 다계정 동일 message ID·실패 격리·중지/해제/재연결 세대 차단을 확인했다. Chromium에서 키 누락→저장 완료→재처리 거부/실패→이전 인덱스 보존→복구와 실패 시 접수 안내 제거·업로드 목록 상태 갱신을 확인했다. 기존 원문 수정/409 입력 보존·모바일 검증도 유지한다. PC·서버 푸시·승인 발송 회귀를 포함하며 실제 계정/과금·운영 확인은 #157·#178에 남는다.

- 지식 문서·PO·CI·PL 통합: 최신 main `d124e31`과 화면 경로/문서를 합친 전체 `uv run pytest`는 **1006 passed·2 skipped**, 규칙 검사 경고 0개, 프론트 lint/test(11개)/build/공개 환경 검사 통과다. `test_knowledge.py` 26개와 실제 Chromium의 `test_knowledge_browser.py`는 합성 파일·실제 pgvector/FastAPI/React와 가짜 비전/임베딩/Storage로 업로드→원본 대조→수정/확정→부모/자식/벡터 저장을 확인한다. 누락 페이지 검토 대기·409 수정문 보존·소유자 분리·모델/차원 교체·SQL 교체 실패/부분 배치 실패의 이전 결과 보존·임대/늦은 시도 차단을 검증했다. Word/Excel/TXT 한글 렌더 결과와 1440/390px 화면도 직접 확인했다. 실제 AI 정확도·비용·운영 DB/Storage/Render 확인은 #178에 남는다.

- 병합된 PR #189의 PO 화면을 가상 데이터 Edge에서 1440·768·390px로 확인했다. 주소 누락·상품/단가 불일치·EUR 매입 단가 부재의 화면 안내, 수정 후 USD 매입 단가 3과 할인/무상 반영 합계 27, 검토 취소의 키보드 실행, ID 재개를 확인했다. 재현 결함은 없어 화면·업무 코드는 바꾸지 않았다. 이번 브랜치의 Linux·임시 PostgreSQL 전체 `uv run pytest`는 **979 passed·2 skipped**, 규칙 검사는 경고 0개, frontend test/lint/build도 통과했다. Windows 전체 실행은 DB 복사 파일 잠금·심볼릭 링크 권한·로컬 Gmail 종료 실패로 중단했으며 PO 작업과 분리한다. 이전 가상 PO의 추출·검토·발급 해시·409 입력 보존 근거와 이번 확인 범위는 [검증 기록](test-records/20261113_po_ci_pl_screens.md)에 구분해 적었다. 실제 계정·운영 연결은 확인하지 않았다.

- PR #190 병합 커밋 d124e31 기준 CI 프런트 helper 검사 11건과 서버 검사 28건이 통과했다. 가상 CI 화면을 1440·768·390px에서 확인했다. 390px에서 PI 목록 네트워크 실패와 목록 다시 읽기, 네트워크 복구 뒤 목록 재표시를 확인했다. 선적 입력칸에서 Tab 이동 후 문서번호와 선적 참조 값이 유지됐고 런타임 오류 표시는 0이었다. 768px에서 PI-MISSING은 구매자 주소 보완과 PI 승인·파일 발급을 남은 작업으로 안내하고 CI 생성을 막았다. 단독 CI 초안 8은 품목 수량 누락 경고로 최종 검토 생성이 막혔다. 이는 필수값 차단의 정상 동작이었다. 단독 CI 문서 6은 추출 근거 충돌로 발급 경로에 쓰지 않았다. 별도 가상 단독 CI 초안 8에서는 검토 생성 뒤 수정 경로와 동시 편집 409를 확인했다. 오래된 탭에서 저장한 `3 Fiction Ave, Seoul`은 화면에 남았고 최신 문서를 다시 확인하라는 안내가 나타났다. 오프라인에서 발급 PDF/XLSX 다운로드 실패 안내를 확인한 뒤 온라인 복구 후 재시도해 HTTP 200과 각 파일의 브라우저 다운로드 완료를 확인했다. 코드 수정은 없었다. 상세는 [검증 기록](test-records/20261113_po_ci_pl_screens.md)에 있다.

- Windows 테스트 환경 오류를 최소 수정했다. SQLite 임시 복사본의 migration 엔진을 즉시 닫고, Windows `npm.cmd` 빌드와 강제 종료 동작을 테스트에 반영했다. symlink 검사는 권한이 비활성화된 Windows에서만 건너뛴다. LibreOffice·Playwright Chromium·frontend 의존성을 준비한 뒤 전체 `uv run pytest`는 **1037 passed·3 skipped**, frontend test 11개·lint·build·환경 검사와 규칙 검사는 통과했다. Linux 컨테이너에서는 워커 6개와 Gmail 종료 1개를 분리 재검증해 통과했다. 첫 전체 컨테이너 실행은 Node 미설치 등 준비 부족으로 실패했으며 최신 전체 Linux 결과는 PR 필수 검사에서 확인한다. 상세는 [검증 기록](test-records/20261113_po_ci_pl_screens.md)에 있다.

- 당시 main `f046d24` 통합 뒤 Linux·임시 PostgreSQL 전체 `uv run pytest`는 **979 passed·2 skipped**다. Windows 전용 2건만 건너뛰었고, PO·CI·PL·단독 CI·PI 번호 중복·XLSX 재시도·PC 프로세스 회귀를 포함한다. `uv run python -X utf8 .work/check.py` 경고 0개, frontend lint·11개 입력 검사·build도 통과했다. 실제 계정·운영 연결과 CI/PL 화면의 모바일/추가 오류 경로는 별도 확인이 필요하다.

- XLSX 발급 재시도 검사에서 같은 내용의 ZIP 생성 시각이 달라 저장소 객체 재사용에 실패했다. ZIP 내부 시각만 고정하는 이전 승인 수정과 직인 유무별 재발 방지 검사로 보완했다. 발행일·셀·이미지·압축 방식과 이미 발급된 파일은 바꾸지 않는다. 실패한 PostgreSQL 검사와 렌더러 검사 11건을 다시 실행해 통과했다.

- PI 번호 중복 검사 추가 뒤 Linux·임시 PostgreSQL 전체 `uv run pytest`는 **930 passed·2 skipped**다. 직접 생성·원문 추출·기존 버전 번호·동시 생성·사용자 분리와 미입력 초안은 별도 검사했다. 중복 안내의 실제 브라우저 확인은 진행하지 못했다.

- PO·CI·PL 로컬 구현: 전체 `uv run pytest`는 Linux·임시 PostgreSQL에서 **926 passed·2 skipped**, 입력 helper 10개·frontend lint/build·규칙 검사(경고 0개)와 React 서버 렌더 검사를 통과했다. CI 목록의 세 상태·버전 고정·중복/페이지/소유권·AI 전 선행 검증, 무역 API 회귀와 발급 파일 해시를 확인했다. 세부 근거는 [검증 기록](test-records/20261113_po_ci_pl_screens.md)에 둔다. 브라우저 재개 후 PO·CI·PL의 주요 발급 흐름과 PO의 409 입력 보존을 확인했다. CI/PL의 1440/768/390px·키보드와 추가 오류·수정 경로는 미확인이다. API/서버 렌더 통과를 브라우저 완료로 표시하지 않는다.
- 이후 사용자 결정에 따라 PI 목록을 최신 버전으로 제한하고 단독 CI를 추가했다. Linux·임시 PostgreSQL 전체 검사는 **927 passed·2 skipped**였고, 마지막 단가 확인 보강은 별도 Windows API 검사로 통과했다. 브라우저의 가상 데이터로 판매 단가 8·합계 80을 확인하고 PI 없이 검토·발급까지 진행했다. PDF의 유상/FOC 분리와 다운로드 파일 해시도 API 검사로 확인했다. 운영 환경 검증은 아니다.

- HTTP 도메인 재배치 당시 검증: `python3 .work/check.py`(경고 0개), 전체 `uv run pytest` **917 passed·2 skipped**, frontend lint/test(4개)/build를 통과했다. 이동 전후 등록 라우트 109개의 URL·메서드·이름과 OpenAPI 명세가 같다. 실제 Chromium·임시 PostgreSQL·가짜 Gmail로 공개/인증 경로, 받은메일·후보 승인 1회, 견적 단가 보완/PDF, 성찰 설정, 개인 키 CSRF/저장/삭제, 실행 기록/마스킹 내보내기와 390px 화면 렌더링을 확인했다. 구조도도 Mermaid로 렌더링했다. 운영 API 확인과 구분하며 위치·유지 조건은 [도메인 안내](domain-layout.md).

- 업무별 마스터·최신 main(`0cafd0d`) 통합: `python3 .work/check.py` 경고 0개, 전체 `uv run pytest` **967 passed·2 skipped**. 신규 44개 사례는 실제 StateGraph/interrupt/체크포인트, 승인/취소/소유권/불명 실행의 조회 복구, 일정 조건/충돌/미연결, 기존 서비스의 PI/PO/CI/PL 발급과 메일 발송을 검증한다. 문서 발급 → 실제 file_ids 바인딩 → 메일 MIME 첨부의 bytes 해시 일치 → 독립 일정 조회도 확인했다. 가짜 Calendar/Gmail/Storage와 실제 임시 PostgreSQL을 사용하며 실제 외부 API·운영 saver·새 UI 연결 검증과 구분한다.

- React PI: `frontend/`의 `npm test`는 원문 추출 후 빈칸만 질문·완료 단계 건너뛰기·미확인 상품군/0원 샘플 구분·십진수 입력 보존을 확인한다(4개 통과). 해당 화면의 lint/build 검증을 통과했다. 실제 FastAPI·임시 PostgreSQL·가짜 Storage/OpenAI의 브라우저 흐름으로 직접 작성/원문 누락 보완/품목 표 수정/재검토/승인, 발급 PDF·XLSX 해시 일치와 409 때 입력 보존을 확인했다. 1440·768·390px 화면에서 배치와 가로 넘침도 확인했다. 실제 OpenAI·운영 Supabase DB/Storage 연결 검증과 구분한다. 기존 전환 범위·제한은 [전환 진행 현황](plans/react-supabase/PROGRESS.md).

- 기준 코드 `c6b1600`의 최근 병합 PR #163은 Linux 전체 **829 passed·4 skipped**를 기록했다(선택 PostgreSQL 모듈 2개·Windows 전용 검사 2개 제외). GitHub [CI 실행 43167274015](https://github.com/encore-ai-campus/aio-03-p2-team3/actions/runs/43167274015)의 `rules-check`·`tests`·`pr-check`·`windows-worker` 모두 성공을 직접 확인했다. Windows 작업은 자격증명·실행기·실제 HTTPS 프로세스 시험을 실행한다. 자동/모의 검증 통과와 실제 API/운영 검증은 별개다.

| 작업 영역 | 확인할 시험·근거 |
|---|---|
| 업무별 마스터·일정·승인/복구·문서/메일 어댑터 | `tests/test_domain_graph.py`, `tests/test_domain_graph_adapters.py` (Calendar 미연결/가짜 공급자, 실제 임시 DB·가짜 Gmail/Storage) |
| 메일·승인·견적·성찰·기억 | `tests/test_{auth,gmail_push,mail_analysis,deal,approval,quote,reflect,memory}.py`, `test_graph.py` |
| OpenAI·로컬·PC·Windows | `test_llm.py`, `test_openai_keys.py`, `test_local_openai.py`, `test_local_gmail.py`, `test_worker_{queue,execution,process,credentials}.py` |
| 무역 계산·발급·버전·회귀 | `tests/test_trade_*.py`, `test_pi_*.py`, [무역 검증 기록](test-records/20261111_trade_domain_api.md) |
| 실제 임시 PostgreSQL | `uv run --with pgserver==0.1.4 pytest tests/test_worker_postgres.py tests/test_trade_postgres.py -q`. PR #162의 두 모듈 8개 통과는 모의 DB가 아닌 임시 PostgreSQL 결과다. |

- 시험 실행기 `app/evaluation/`는 정상 일반/견적·정보 부족·Gmail 오류·OpenAI 한도·도구 오판·환각의 7개 시나리오를 성찰 끔/켬으로 비교한다. 지표는 완료율·도구 선택 정확도·응답 일관성·평균 재시행 횟수다. 고의 주입은 `detail.injected`로 표시하고 실제 API 결과와 구분한다(#92·#93). 실행 조건·명령은 [TEST_REPORT](TEST_REPORT.md) 2~5절, 실제 측정/보고서는 gmail-quote-mvp 18·19절이다.
- 실제 API 확인 이력은 [2026-11-10 일반 문의 기록](test-records/20261110_live_general_result.md)(#97)에 있다. 당시 Gmail·Gemini로 일반 문의의 후보 생성→승인 발송을 확인한 결과이며, OpenAI 성능이나 모든 시나리오 검증 결과로 쓰지 않는다. 현재 OpenAI 전환 후 지표·최종 보고서 완료는 이 근거만으로 확인되지 않는다.
- PC 프로세스 시험의 서비스 HTTP 대기는 큐 전체 120초 기한에 응답 여유를 더한 125초(연결 5초)다. 지연된 모의 503도 세 번 재시도한 뒤 `WORKER_NETWORK`를 반환하며 문서 미생성·payload/result 삭제를 검증한다. SDK/서버의 운영 한도는 유지한다([원인·재현 기록](test-records/20261113_worker_process_readtimeout.md)).
- 개인 PC 실제 연결·키 교체/삭제·두 사용자 과금 프로젝트·Render 종단 간 확인은 [#157](https://github.com/encore-ai-campus/aio-03-p2-team3/issues/157)(조회 시 open), 로컬 실행 계획 5절에서 미확인이다. 코드/모의 HTTP/브라우저/Windows CI 통과를 이 완료로 표시하지 않는다.
- 과거 시험별 상세 결과와 구현 경위는 각 병합 PR, `docs/test-records/`, [축약 전 문서](https://github.com/encore-ai-campus/aio-03-p2-team3/blob/c6b16007f824450fc5cfd23e77da877beaf87930/docs/PROJECT_CONTEXT.md)에 보존돼 있다. KE KOREA 원본 동일성·알려진 오류 점검 기록은 `test-records/20261110_kekorea_port_err_check.md`다.

## 7. 배포
마지막 갱신: 2026-11-19 · 수신 근거·계약 연결 마이그레이션, 기능별 모델 상향 환경변수

- 기능별 모델 상향(오류 대응용): Render Environment에 `LLM_PROFILE_DEFAULT_STRUCTURED`/`LLM_PROFILE_TRADE_EXTRACTION`=`sol-medium`, `LLM_PROFILE_VISION_TRANSCRIPTION`=`terra-low`를 넣으면 재배포 뒤 새 호출부터 적용된다. 비우거나 지우면 baseline, `luna-medium`은 명시 복귀다. 잘못된 이름은 배포 시작 실패로 나타난다. 본인 키 프로젝트에 상향 모델 권한·요금이 필요하다. 절차는 README 'LLM·외부 API와 키 발급'.

- `20261119_inbound_context`는 기존 문서함에 계약 거래처 연결, 키워드 검색 인덱스와 수신 메일 근거 필드를 추가한다. 기존 문서는 연결 정보를 비워 두고 문서함 상세에서 설정한다. 운영에서 수신 확장은 로컬 실행 또는 서버의 저장된 사용자 키 경로를 사용한다. 기존 개인 PC 프로토콜 v1은 분류 v2를 유지하며 문서함 임베딩은 지원하지 않는다.
- `20261119_chat_mail`이 사용자별 새 메일 초안과 후속 알림 표를 추가한다. 앱은 시작 시 및 60초마다 수집된 답장을 확인하며, 사용자 화면은 기한 도달 알림을 30초마다 확인한다.

- PI·PO·CI·PL 모바일 후속 범위는 [모바일 전환 계획](plans/trade-mobile-workspaces.md)에 공통 배치/PI·PO → CI 연결·단독 → PL/4종 회귀의 3개 순차 작업으로 나눴다. PR #205의 보류 기록과 기존 600/800/1100px 반응형을 출발점으로 삼는다. 1절의 공통 모바일 배치와 PI/PO 입력·검토 보완 및 브라우저 검증을 구현했다. 2절 CI 연결/단독도 공통 요약·오류/단계 포커스·입력 보존과 브라우저 발급 검증을 마쳤다. 3절 PL 포장/대조/검토 UI와 4종 브라우저 회귀도 구현했다. 실제 기기 키보드와 운영 연결은 미확인이다. 공통 높이·sticky 작업 버튼·스크롤/포커스 규칙과 재검증 방법은 계획 1절을 재사용한다. 기존 #143의 PL 업무 검증·#149의 전체 앱 통합 검증·#150의 실제 운영 전환을 완료 처리하지 않는다.

- 대화형 API는 기존 DATABASE_URL에 대화 표와 공식 체크포인트를 저장한다. 앱 시작의 Alembic이 소유권 표를 준비하고 최초 대화 실행 때 saver가 public 표 4개를 준비해 RLS/공개 역할 접근을 제한한다. 실행 중 재시작은 interrupted로 남기고 본인의 명시적 상태 확인으로 이어간다. 운영 DB 적용/실제 모델·발송 확인은 별도다.
- 단독 CI 작성은 `/app/trade/ci/standalone`과 `/app/trade/ci/standalone/{id}`를 사용한다. 기존 PI 연결 CI는 기존 주소를 사용한다. 실제 운영 연결은 확인하지 않았다.
- Render 설정 기록(2026-11-10): `https://aio3-gmail-quote.onrender.com`, 무료·Singapore·main 병합 시 자동 배포, 빌드 `uv sync --locked`, 시작 `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`. 당시 설정 기록이며 이번 문서 갱신에서 현재 운영 상태를 재확인하지 않았다.
- 계획 21.1절(#149)은 6·7절을 선행으로 UI 개발과 병행한다. `render.yaml`·`scripts/render-build.sh`가 `uv sync --locked` → `npm ci --include=dev` → `npm run build`와 기존 서버 시작을 연결한다. FastAPI는 `frontend/dist`만 `/app/`에서 제공하며 상세 주소는 `index.html`로 복구하고 누락 자산은 404로 반환한다. `/api`·Google callback·Gmail Pub/Sub·공개 약관·기존 `/static`과 `/`→`/inbox`는 유지한다. 빌드가 없는 개발 환경에서도 서버는 동작하고 UI만 503이다. `frontend/` 파일은 수정하지 않았다. Dashboard 관리 서비스에는 README 절차대로 Build Command/Node 버전을 적용해야 하며 실제 Render 설정·배포 커밋·운영 응답은 미확인이다. 전체 UI 통합 검증/진입 전환은 20절 뒤 21.2절, 실제 운영 전환은 사람의 22절이다. #149는 후속 검증까지 열어 둔다.
- 배포 기반 검증은 전체 PostgreSQL `uv run pytest` 923 passed·2 skipped, 규칙 검사 경고 0개, 프론트 lint/test/공개값 검사·실제 빌드와 Chromium smoke를 통과했다. 상세 주소/자산·콜백/알림 경로와 서버 비밀값 제외 근거는 [진행 현황](plans/react-supabase/PROGRESS.md)의 21.1절에 있다. 전체 UI 완주·실제 운영 성공과 구분한다.
- 앱 DB는 PostgreSQL 전용이다. `DATABASE_URL`이 비었거나 비PostgreSQL이면 시작을 거부하며 SQLite 자동 생성은 없다. Alembic 대상은 `public`으로 고정해 Supabase `auth`·`storage`를 건드리지 않는다. `20261112_react_worker_merge`가 Supabase 전환/기존 worker 분기를 합친다. 운영 반영 전 DB 백업과 기존 `TOKEN_ENCRYPTION_KEY` 유지가 필요하다. SQLite 등 기존 원본은 `app.db.copy_data`, 회사 이미지/발급 바이너리는 backfill 명령으로 복사·해시 검증하며 원본·바이너리 열은 아직 삭제하지 않았다([전환 계획](plans/react-supabase/PLAN.md) 4·9·10·22절).
- `20261116_mail_triage`는 캘린더 OAuth 변경 뒤 기존 메일 표에 nullable 분류 결과를 추가한다. 기존 메일은 자동 재분류하지 않으며 운영 DB 적용은 별도 확인한다.
- `20261118_query_indexes`는 자주 읽는 조회 경로(메일함 스레드 집계·원문 조인, 스레드 후보, 실행 기록·무역 문서·문서함 목록, 거래 기억, PC 큐, 저장소 정리)에 복합 인덱스와 시작 복구용 부분 인덱스를 추가한다. 새 DB는 create_all이 같은 정의를 만들고 기존 운영 DB는 이 리비전이 채운다. 정의 원본은 `app/db/models.py`·`app/knowledge/repository.py`다.
- `20261118_calendar_receipts`는 일정 등록 멱영수증 표(`calendar_event_receipts`, RLS 포함)를 추가한다. 앱 시작 Alembic이 만들며 실제 Google Calendar 등록 확인은 #157과 구분해 사람이 확인한다.
- `20261113_knowledge_ingestion`은 문서·부모·자식 vector 표를 더하고 RLS/직접 공개 권한을 제한한다. vector 확장을 create_all보다 먼저 준비하며 기존 확장 스키마를 존중한다. CI PostgreSQL 16은 고정한 pgvector 이미지, Windows는 고정 소스 빌드를 사용한다. Office/TXT에는 LibreOffice가 필요하고 PDF/이미지는 고정 PDFium/Pillow로 읽는다. 설치/시험 명령·KNOWLEDGE_* 설정은 README/`.env.example`, 실제 운영 vector/버킷 제한·LibreOffice·모델 권한/정확도/과금 확인은 문서 수집 계획 2절/#178에 남아 있다. 운영 DB/배포·실제 문서 API 호출은 이번 구현에서 실행하지 않았다.
- 무료 서버는 15분 미사용 시 잠들 수 있고 재시작/배포 때 로컬 파일을 잃으므로 운영 데이터는 Postgres에 둔다. 2026-11-10 생성한 무료 Postgres는 당시 안내상 12/10경 만료·14일 유예 후 삭제 예정이었다. 현재 요금제·보존 상태는 운영 담당자가 확인한다.
- 서버 `stored_key`는 본인 로그인 후 `/settings`에서 키를 등록한다. 서버 `OPENAI_API_KEY` 대체는 차단돼 있다. `local_worker`는 개인 PC가 켜져 있고 같은 모델/설치 정의로 연결돼 있어야 한다. 메일·문서 입력과 AI 결과는 서버를 거치지만 PC 키는 서버에 전송/저장하지 않는다. 키를 지우거나 PC를 중지해도 이미 외부 API에 전송한 요청의 취소를 보장하지 않는다.
- LOCAL_OWNER_GOOGLE_SUB는 app.worker.pc의 명시적 개인 파일/LocalPolicy에서만 읽는다. 앱 공통 Settings와 로컬 화면의 식별자 복사 안내는 제거했다. 서버 PC 연결 화면의 본인 Google 식별자 대조와 Gmail 연결 계정 일치 검사는 유지한다. 지식 문서는 로컬 키/리스너 설정 오류를 정확히 안내하고, 처리 실패 뒤 이전 접수 안내를 숨긴다.
- 로컬 AI는 Google/Gmail 연결 없이 `AI_RUNTIME=local`·`.env` 키와 `uv run python -m app.local`을 쓴다. 실제 리스너는 `127.0.0.1` 전용이고 공용 Uvicorn/Render 시작은 거부한다. Gmail 수집은 개인 Google OAuth·루프백 콜백과 별도 로컬 DB에서 refresh 토큰·local:history·활성/재시도 상태가 있는 user_id들만 순차 처리하며 Pub/Sub 토픽 없이 연결한다. 운영 DB·암호화 키·OAuth 비밀값을 개인 PC로 복사하지 않는다(#159·#160·#157).
- 서버+PC 방식은 `uv run python -m app.worker.pc pair`로 본인 HTTPS 서비스와 연결 승인 후 `run`으로 실행한다. 개인 환경 파일·서비스 주소·검증된 본인 Google 식별자를 지정하고, 키 교체 뒤 재시작한다. Windows PowerShell도 WSL 없이 지원한다(#163). 설치·`--env`/`--credentials`·중지·재연결·문제 해결은 [README](../README.md)의 개인 PC 실행 안내에 있다.
- React 앱은 `frontend/`의 JavaScript/Vite이며 개발은 `npm ci` 후 `npm run dev`(`/app`, `/api` 프록시)다. 루트 `.env`의 `FRONTEND_PORT`가 개발 포트이며 비우면 5174, 지정하면 그 포트만 쓴다(사용 중이거나 올바르지 않으면 실패). 로그인 반환 주소는 실제 포트의 `/app/login`과 맞춘다. `/app/settings`에서 회사·거래처·판매/구매 단가·통화별 계좌·로고/직인을 저장한다. 기존 API를 재사용하고 거래처 저장만 추가했다. 실패 입력 보존·조회 취소·이미지 객체 URL 정리를 두며 새 설정은 기존 제안/발급 파일을 바꾸지 않는다. PI는 `/app/trade/pi`·`/app/trade/pi/{id}`에서 작성 방법 선택 → 거래처/판매자/품목/거래 조건 → 전체 확인 → 검토/승인/다운로드로 진행한다. 원문 추출 결과와 설정 기본값을 보존하고 필요한 빈칸만 질문하며, 채워진 내용도 단계별 전체 수정에서 바꿀 수 있다. 품목은 표로 편집하고 규격·할인·샘플은 접어 둔다. 오른쪽 작성 요약은 모바일에서 펼쳐 보고, 전체 문서는 마지막에 한 번만 표시한다. 금액·가격 확인·revision/해시 검토·발급은 기존 서버 API를 그대로 쓴다. 버전 충돌 때 입력을 보존하며 최신본 재조회와 재검토를 안내한다. PI/PO 원문은 작성 방법을 왕복해도 보존하고 오류 안내로 포커스를 옮긴다. 하단 탐색·본문 여백·작업 버튼은 safe-area를 포함한 공통 높이를 쓰며 화면 크기 변경은 폼 DOM·단계·요약을 재생성하지 않는다. 고정된 회사 이미지는 소유자·문서·제안 범위 읽기 API로 확인하고, 개인 키 관리는 기존 서비스를 Bearer API로 연결했다. PO·CI·PL은 13~15절대로 같은 작성 카드의 링크와 `/app/trade/{po|ci|pl}`·`/app/trade/{kind}/{id}` 경로를 로컬 연결했다. CI의 PI 선택/미승인 작성 준비와 PL의 별도 합계 확인을 포함한다. CI의 두 작성 경로는 같은 접이식 요약과 단계/오류 포커스를 사용한다. PI 상태 재확인·명시적 새 버전 선택에도 선적 입력을 보존하며, 단독 CI는 누락/단가 확인 보완 버튼과 최초 저장 뒤 입력/요약 유지 처리를 둔다. PI/PO·CI 연결/단독·PL 직접/가짜 추출의 390px 발급 완주를 확인했다. PL 원문 보존·오류 포커스와 이름 있는 원본/계산 스크롤 영역을 제공하며 두 승인 계약은 유지한다. 실제 운영 연결과 전체 UI 통합 검증은 남아 있다. 업로드 문서함은 기존 지식 문서 화면을 통합해 연결했다. 원래 계획 16절의 무역 초안/발급 이력 목록과는 구분하며, 메일/현황 등은 17~20절, 전체 UI 통합 검증은 21.2절 후속 작업이다.
- React 개발 화면의 Gmail·Calendar 연결은 기존 `FRONTEND_ORIGINS`의 첫 출처로 콜백 결과를 돌려준다. 예: React `http://127.0.0.1:3000`, Google 콜백 `http://127.0.0.1:8000/auth/google/callback`. 루프백 호스트 불일치(localhost↔127.0.0.1)는 어느 연결이든 Google 이동 전에 400으로 안내하고 포트 차이는 허용한다. 출처가 없으면 기존 상대 주소를 유지한다. React·Vite 추가 프록시와 토큰 저장/인증 검증은 유지한다. 메일함의 수집/발송 검증은 [기록](test-records/20261116_mailbox.md)에 실제 Gmail과 모의 검사를 구분한다.
- Supabase 로그인은 `SUPABASE_URL`의 JWKS로 Bearer 서명·issuer/audience·만료·UUID를 검증해 기존 정수 사용자 ID에 매핑한다. `/api/me`·`/api/gmail/*`·`/api/files*`와 무역/설정 API를 연결했으며 잘못된 Bearer가 쿠키 세션으로 우회하지 않는다. legacy 로그인/CSRF는 전환 기간 유지한다. Gmail 연결은 state·PKCE·같은 Google 공급자 subject를 확인하고, 앱 로그아웃은 Gmail 수집·토큰·커서를 유지하고 설정의 연결 해제 때 중지/폐기한다(계약 9.1절). 서버 lifespan 작업이 화면 방문 없이 감시 갱신과 새 미완료 분류 복구를 확인한다. 지원 범위는 단일 앱 프로세스다. `/app/settings`의 로고·직인 아래 `연동하기`에서 Gmail 연결·재연결·확인 후 해제를 제공하고, Google 캘린더는 본인 계정의 별도 읽기 전용 OAuth와 목록 조회 검증 뒤 연결한다. `calendar_tokens`·일회성 DB state를 Gmail과 분리하며 Calendar만 연결할 때 Pub/Sub는 필요 없다. Calendar 해제는 앱 토큰만 삭제하고, Gmail 해제/Google 전체 권한 철회 뒤에는 공급자로 재검증한다. 회사 설정 조회 실패에도 메뉴/카드를 열 수 있으며 콜백은 연동 항목을 자동 선택하고 `/api/me`를 재조회한다. URL 결과는 안내 뒤 소비하며 실제 연결·감시 상태는 서버 응답으로 구분한다. 401·설정 누락·취소·권한/계정 오류·감시/해제 실패에는 로그인 복구 또는 상태 재조회를 안내한다. 서비스별 인증 조회·오류·해제의 재사용 경계는 [연동 계획 1절](plans/settings-google-integrations.md#1절-구현-결과와-재사용-경계)에 있다. Calendar의 만료 토큰은 갱신하고 철회·권한 부족은 재연결, 공급자 장애는 Gmail과 분리한 미확인으로 표시한다. 실제 Google/Render 연결 확인은 #193에 남는다.
- `web/routes`와 `web/deps.py`는 제거하고 HTTP 진입점을 `auth`·`mail`·`settings`·`quote`·`runlog`로 옮겼다. `web`에는 공개 페이지·공유 템플릿·정적 자산만 둔다. 공통 인증/폼 CSRF는 `auth/deps.py`에서 제공해 무역 API·worker가 화면 모듈을 import하지 않는다. 기존 URL·세션/Bearer 우선순위·승인·DB 의미는 유지한다. React 실행기록·전체 UI 통합 검증이 미완료라 기존 HTML 자산은 아직 필요하다([이동표·유지 조건](domain-layout.md)).
- 첨부·회사 이미지·승인 PDF/XLSX의 bytes는 private Storage, 소유자/참조/해시는 PostgreSQL에 둔다. 모든 형식 업로드 뒤에만 문서 승인 SQL을 확정한다. 새 XLSX는 ZIP 내부 시각을 고정해 같은 검토 내용의 재시도에서 같은 해시·객체 key를 사용한다. 발행일과 기존 발급 파일은 유지한다. 발급 객체 재사용·backfill·수동 정리는 같은 객체별 PostgreSQL 트랜잭션 잠금으로 조율하고 삭제 전 참조를 다시 확인한다. 상세 파일 계약/제한/이전 명령은 계약 16.3절과 README다.
- 공용 OAuth·Gmail Pub/Sub·OIDC/대체 토큰은 유지한다. 로컬은 watch/stop을 호출하지 않는다. 문서/설정 API는 Bearer 또는 기존 세션/CSRF로 소유자를 검사하고, 장치 승인과 장치 통신의 기존 CSRF·장치 토큰 계약은 유지한다. 환경변수 원본은 `.env.example`·계약 11절이다. Supabase는 루트 `.env`의 `SUPABASE_URL`·`SUPABASE_PUBLISHABLE_KEY`·`SUPABASE_SECRET_KEY` 세 값으로 설정하며 Vite는 URL과 공개 키만 브라우저에 제공한다. `frontend/.env`와 중복 URL은 제거했고 버킷은 기본 `trade-files`다. 실제 DB 연결용 `DATABASE_URL`은 별도로 필요하다. `frontend/`의 `npm run check:env`로 공개값 전달·비밀값 빌드 제외를 확인한다. 프로젝트·비공개 버킷·Google OAuth 준비는 사용자 확인이며 로컬 Supabase URL/키와 개발 포트를 설정했다. Auth 설정 조회·Google 로그인 시작은 확인했고, 실제 계정 로그인·Gmail·운영 DB/파일 이전은 미확인이다. 현재 로컬 DB는 임시 PostgreSQL이며 실제 DATABASE_URL과 Google/암호화 설정은 별도로 확인해야 한다.
React 무역 문서에서 PI·PO·CI·PL 최신 설정 적용과 누락 입력 팝업을 구현했다. 화면은 `frontend/src/trade/ReviewPanel.jsx`, `MissingFieldsDialog.jsx` 및 각 문서 페이지, API는 `app/trade/common/operations.py`와 도메인 operations/router에 있다. 상세 범위는 [계획](plans/trade-document-settings-and-missing-fields.md)이다. 기능 변경 후 검증은 별도 요청 전까지 보류한다.

- 운영·실제 API 확인은 #157, [로컬 실행 계획](plans/local-openai-execution.md) 5절과 gmail-quote-mvp 16·18절에 남아 있다. Codex의 역할은 코드/병합 근거·자동/모의 검사·실행 절차 준비까지이며, 테스트용 Google 계정·가상 메일을 쓰고 실제 키 입력·Google 동의/장치 승인·본인 PC 실행·과금/운영 변경은 사람이 한다.

## 8. 문서·산출물 위치
마지막 갱신: 2026-11-19 · 업무 채팅 결과 화면과 수신 메일 검증 기록·LLM 측정/프로필/카탈로그 후보 계획 위치

| 무엇 | 위치 | 상태 |
|---|---|---|
| 과제 요구사항 정리(R-ID·D-ID) | `docs/REQUIREMENTS.md` | 있음(2026-11-09) |
| 업무별 마스터·메일·문서·일정의 현재 계약 | `docs/CONTRACT.md` 2.1·3.0·17절 | 구현과 연결 경계·정상/실패 시험 명시 |
| 에이전트 아키텍처 설계서 | `docs/ARCHITECTURE.md` | 초안 있음(최종 코드와 맞춰 20에서 고침) |
| 팀원용 도메인 구조도·파일 이동표 | `docs/domain-layout.md` | LLM/Google 역할 비교, HTTP 도메인 위치, web 자산 유지 근거·대체 조건 |
| 에이전트 시험 결과 보고서 | `docs/TEST_REPORT.md` | 틀 있음(2026-11-10, 시나리오·판정 기준·시험 환경. 결과는 18·19) |
| 시험 실행 기록(실행마다 한 파일)·실제 API 확인 결과 | `docs/test-records/` | 있음(2026-11-10, #62 1번 일반 문의 흐름: 실행 기록 3개와 결과 문서) |
| 큰 작업의 계획 파일 | `docs/plans/gmail-quote-mvp.md` (형식: `docs/plans/README.md`) | 있음(Gmail 견적 MVP 구현 계획) |
| 대화형 마스터 업무 도우미 | `docs/plans/master-agent.md`·계약 17.4절·`app/graph/`·`frontend/src/agent/` | 기존 마스터의 도구 반복·본인 API·PostgreSQL 저장·대화/질문/승인 화면을 로컬 연결. 실제/모의 검증 경계는 계획 3절에서 구분 |
| 업무 채팅 도구와 결과 화면 | `docs/plans/chat-workflows.md` | 1~9절 완료. 일정 변경·취소, 새 초안·기존 답장 편집, 미완성 무역서류, 원본 첨부, 후속 알림까지 채팅에 연결. |
| 수신 메일 기능 공백 점검 | `docs/test-records/20261119_inbound_company_audit.md` | 가상 거래처 8곳의 수신 그래프 실모델 결과와 후속 구현 우선순위. |
| 업무 도우미의 문서 검색 | `docs/plans/agent-document-search.md` | 1절 발급 무역 문서 DB 검색과 2절 문서함 파일·조항 검색 구현 |
| LLM 품질·비용 측정, 기능별 모델 프로필, 카탈로그 후보 계약 | `docs/plans/llm-quality-and-cost.md`·`llm-model-profiles.md`(+`.contract.json`)·`catalog-candidates.md` | 측정기·PC 선별 40회 실측, 두 계약은 초안(운영 미적용) |
| Google Calendar 실연동(조회·등록) | `docs/plans/calendar-port.md` | 1~3절 구현 완료. 설정 연결 토큰으로 ExistingCalendar 어댑터가 freebusy·등록·확인을 실제 Google에 실행하고(main 주입), 영수증 표로 멱등·타임아웃 복구를 지키며 업무 도우미의 find_slots·create_event 도구로 대화에서 쓴다. 실제 Google·운영 확인은 요청자 브라우저·#157에 남음 |
| 회사 메일함·업무 분류·로그아웃 후 수집 | `docs/plans/mailbox.md` | 1~5절 로컬 구현·검증 완료. 로그아웃 후 수집 유지, 확실한 무관 메일만 Decisions 제외, 나머지는 기존 그래프, Bearer API·React 원문/초안/최종 수신자 확인·기존 승인 발송을 연결했다. 그래프 상태/엣지·수집기·React 3000/FastAPI 8000은 유지한다. 실제 Decisions 합성 시험·Gmail 연결/시험 발송과 외부 테스트 메일 수신·기존 그래프·후보 생성을 확인했다. 사용자 위임 뒤 가상 단가 확정·선택 후보의 실제 Gmail 답장/PDF·동일 스레드·중복 발송 방지를 확인했다. 운영 연결·FOB 문서 판단·분류 품질의 제한은 5절과 시험 기록에서 구분한다. |
| 지식 문서 수집·pgvector 저장 | `docs/plans/document-ingestion.md`·계약 18절·`app/knowledge/`·`frontend/src/knowledge/` | 1·3~7절 구현. 사용자 선택 OpenAI 비전/현재 모델 + text-embedding-3-small, 조항 parent-child와 독립 모델 교체·페이지 대조/수정·저장/화면 포함. 실제 pgvector/합성 문서/가짜 AI의 브라우저 시험과 실제 운영 확인을 구분하며 #178은 사람 확인으로 남음. 채팅 검색은 업무 도우미 문서 검색 계획 2절에 연결 |
| 설정의 Gmail·Google 캘린더 연동 | `docs/plans/settings-google-integrations.md` | 1절의 연동 메뉴·기존 Gmail 연결/해제/재연결/상태 UI 구현. 회사 설정 장애 경계·서비스별 조회/해제 계약과 가짜 Google/실제 임시 PostgreSQL 브라우저 검증을 포함한다. 2절 Calendar OAuth/카드 활성화 구현. 서버 일회성 state·별도 암호화 토큰·갱신/계정/실패 격리를 검증하며 사람의 콘솔·Render 확인은 #193에 남음 |
| 개인 PC .env 키로 로컬/Render AI 실행 지원 | `docs/plans/local-openai-execution.md` | 1~4절 로컬 키·Gmail 수집·장치/큐·PC 실행기/기존 AI 연결 구현. 실제 키·Render 연동은 사람의 5절에서 미확인 |
| 로컬 AI·Gmail 계정 결합 정리 | `docs/plans/local-runtime-simplification.md` | 1~3절 구현. 로컬 AI는 전용 루프백/환경 키, Gmail은 연결·활성 user_id 순차 수집, LOCAL_OWNER_GOOGLE_SUB는 개인 PC 실행기 전용이다. SQL/조건부 갱신은 작은 Store, 기존 인증·모델 Protocol·서버 키·승인 경계는 유지한다. 실제 API/운영 확인은 기존 #157·#178에서 별도 수행 |
| KE KOREA 무역서류 로직 이식 계획 이력 | `docs/plans/kekorea-port.md` | 1~6절 완료, 참고 이력 |
| KE KOREA 원본 사본(참고 이력, 읽기 전용) | `reference/kekorea/` (담은 것·바꾼 것·원본 테스트 실행법은 그 폴더 README) | 완료한 이식의 원본(ai-agents `8d397a1`, 앱에서 import하지 않음) |
| 무역 문서 API 연결/폴더/승인 흐름 | `docs/trade-api.md`·계약 16절·`docs/plans/trade-domain-api.md` | 1~4절 구현·검증 |
| React·JavaScript·Vite / Supabase 전환 | `docs/plans/react-supabase/`·`frontend/` | 1·3~12절·21.1절 및 13~15절 코드 구현. 13~15절의 일부 브라우저 경로와 운영 연결 검증, 16~20·21.2절과 사람의 22절 남음. 콘솔 준비는 사용자 확인이며 실제 계정 로그인·운영 전환 미확인. 상세 검증/제한은 PROGRESS.md·`test-records/20261113_po_ci_pl_screens.md` |
| 무역 문서 최신 설정 적용·누락 정보 팝업 | `docs/plans/trade-document-settings-and-missing-fields.md` | 1·2절 구현 완료. PI 연결 CI는 같은 PI 문서의 최신 승인 revision 거래 정보를 사용하고, 이름이 일치하는 최신 거래처 프로필만 반영한다. 수기 가격·기존 발급 파일은 보존한다. 기능 검증은 사용자 별도 요청 대기 |
| PI·PO·CI·PL 모바일 화면 전환 | `docs/plans/trade-mobile-workspaces.md` | 기존 반응형/보류 기록을 확인해 공통·PI/PO, CI 연결/단독, PL/4종 회귀의 3개 작업으로 분리한 계획. 1절 공통 배치·PI/PO 입력/검토와 상태 보존·브라우저 회귀 구현. 공통 CSS/표시 컴포넌트 재사용 규칙은 1절, 상세 근거는 기존 검증 기록에 둔다. 2절 CI 연결/단독의 모바일 입력 보존·검토/발급·오류 재시도 검증 완료. 3절 PL/4종 자동 브라우저 회귀 구현. 실제 기기/운영 연결은 미확인 |
| KE KOREA 개인 에이전트 개선 사례·선택 적용 제안 | `Team/README.md` | 참고 제안, 현재 팀 코드와 비교 후 판단 |
| 개인 에이전트 개선 사례 발표용 참고 | `Presentation/README.md` | 참고 자료, 팀 기능 구현 완료와 구분 |
| 발표 PPT | 미정 | 아직 없음 |

- 위치는 Claude가 정한 처음 값이다. 팀이 바꾸면 이 표와 README를 함께 고친다. [Claude proposal]
- 설계 결정·오류 사례·수정 이유·버전·재실행 결과는 Issue, PR('오류·재실행 기록' 칸), 팀 노션에도 남긴다.

## 9. 레포 세팅·작업 방식
마지막 갱신: 2026-11-18 · GitHub CI의 느린 통합 검사 제외

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
- CI: `.github/workflows/rules-check.yml`은 PR 생성/코드 갱신/재개와 `main` push에서 규칙 검사 후 `scripts/ci_scope.py`로 변경 경로를 판별한다. 코드·설정·미분류 경로가 있거나 비교가 실패하면 Linux의 Python/pgvector PostgreSQL 검사와 Windows 개인 실행기·DPAPI·DACL 검사를 실행한다. Linux는 LibreOffice·변환용 한글 폰트·Chromium·프론트 의존성 설치를 생략하고 `uv run --locked pytest -m 'not slow'`를 실행한다. Windows도 실제 HTTPS/PC 프로세스 검사를 제외한다. 잠금 파일 확인과 Python 패키지 설치는 각 작업의 `uv run --locked`에서 수행한다. Linux 20분 한도와 Windows 고정 pgvector 설치를 유지한다. README·지정 문서 폴더의 Markdown·작업 규칙·PR 양식만 바뀌면 테스트와 DB 준비를 생략한다(테스트가 직접 읽는 `docs/TEST_REPORT.md`는 제외). 필수 검사 이름 `rules-check`·`tests`는 유지하고 범위 확인 실패는 `tests` 성공으로 처리하지 않는다. `.github/workflows/pr-check.yml`은 PR 본문/읽음 코드/최신 흐름 기재를 독립적으로 검사해 설명 수정이 이전 테스트 실패를 덮거나 테스트를 다시 시작하지 않는다. 동일 브랜치의 새 커밋은 이전 실행을 취소하며 본문/코드 워크플로는 서로 취소하지 않는다. GitHub의 병합 충돌 판정과 기존 필수 검사 Ruleset은 유지한다.
- 로컬 `uv run pytest`에는 DOCX·XLSX·TXT 실제 변환, Chromium, Gmail 런처·PC 별도 프로세스 시험이 포함된다. 이 시험만 실행할 때는 `uv run pytest -m slow`를 쓴다. Excel 숨김 시트·수식 결과 누락 검사는 CI에도 포함된다. 운영의 DOCX·XLSX·TXT 업로드에는 LibreOffice가 필요하다.
