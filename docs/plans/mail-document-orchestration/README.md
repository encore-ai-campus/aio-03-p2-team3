# Gmail → 멀티에이전트 무역문서 → 사용자 승인 → Gmail 발송 설계

> **2026-11-11 · 설계 전용 · 미구현.** Superpowers `brainstorming`(현황·대안·결정·충돌)과 `writing-plans`(의존 작업·테스트·검증)를 참고한 문서. 이번 작업은 README만 작성하며 **기존 코드·테스트·DB·배포·개인 저장소는 변경하지 않는다**. Superpowers 도구를 실제 설치하거나 실행했다는 의미는 아니다.

**대상 저장소:** `encore-ai-campus/aio-03-p2-team3`, 기준 `main`의 코드와 `docs/CONTRACT.md`, `docs/trade-api.md`. 관련 요구 R-02/R-03/R-04/R-11/R-14; 팀의 상태·도구 공통 계약은 변경하지 않는다. 구현 전 관련 팀원 협의 필요.

## 1. Brainstorming — 재사용할 기존 기능

| 기존 | 확인된 인터페이스 | 절대 지킬 조건 |
|---|---|---|
| Gmail 수신/중복 처리 | `app/services/gmail_push.py` | 기존 메일 ID·thread ID·사용자 분리 유지, 별도 중복 수신 금지 |
| Gmail LangGraph | `app/graph/build.py`, `state.py` | 현재 AgentState/노드/전이 무수정 |
| 답장 승인·메일 발송 | `app/services/approval.py`의 `send_approved_candidate`, `send_approved_quote`, `send_approved_trade_document`; `app/tools/send_email.py` | 기존 승인과 소유자 확인, 같은 스레드 발송. AI가 Gmail 도구 직접 호출 금지 |
| PI/PO/CI/PL | `app/trade/{pi,po,ci,pl,common,review,settings}`, `/api/trade/{kind}` | 기존 계산·단가·정확한 Decimal·출력·revision·사용자별 격리 불변 |
| 문서 승인 | `app/trade/review/operations.py`; `/reviews`, `/decisions`, `/api/trade/files/{file_id}` | 기존 revision/proposal_id/content_hash·취소·수정 검증 유지; 문서 승인과 메일 승인 별개 |
| CI/PL 선행조건 | `docs/trade-api.md` | CI는 사용자 선택의 **승인된 PI 특정 revision**에 종속. PL은 packing-review 합계 승인 이후 문서 최종 승인 |
| Contract | 팀 앱에 개인 KE KOREA와 동등한 계약서 API 미확인 | Contract adapter 기본 `unavailable`; 개인 저장소/기밀 DB 복제나 직접 호출 금지 |

**설계 선택:** 기존 `app/graph`를 확장하거나 `app/trade`를 복제하지 않는다. **새로운 독립 `app/orchestration/` 그래프**를 계획하고, 검증된 기존 API를 이용하는 어댑터로 연결한다. 다른 별도 마이크로서비스는 현재 과도한 복잡성 때문에 보류한다. **기능 기본 OFF**, 초기는 사용자가 명시적으로 실행하는 opt-in 실험만 허용한다. 메일 push에 새 그래프를 자동 병렬 연결하지 않는다.

## 2. 목표 아키텍처 (구현하지 않음)

```text
[기존 Gmail API / Pub/Sub / 파서]
       ├── 기존 Gmail LangGraph 및 승인/송신 (변경 없음)
       └── 신규 opt-in 수동 실행 (자동 이중 처리 금지)
                    ↓
     NEW Master Orchestrator (독립 LangGraph / 독립 State)
        ├─ 요청 분류·근거·누락 검사
        ├─ PI adapter ── 기존 PI API
        ├─ PO adapter ── 기존 PO API
        ├─ CI adapter ── 승인된 PI revision 지정 후 기존 CI API
        ├─ PL adapter ── packing-review 후 기존 PL API
        └─ Contract adapter ── unavailable (API 확보 전)
                    ↓
      문서별 개별 검토·승인·revision 확인
                    ↓
      승인된 첨부 파일의 바이트 SHA256 manifest 고정
                    ↓
      메일 초안: to/cc/bcc/subject/body/thread/attachments
                    ↓
      사람의 별도 이메일 승인 + 전체 envelope 해시 검사
                    ↓
      기존 승인된 발송 인터페이스 사용 가능 여부 확인
                    ↓
       Gmail 1회 발송·이력·불확실 상태 추적
```

제안 파일(미생성): `app/orchestration/{graph.py,state.py,router.py,adapters/,manifest.py,approval_gate.py,runlog.py}`. 기존 내부 함수 직접 사용이나 기존 DB 테이블 임의 UPDATE 금지. **현재 `send_approved_trade_document`는 단일 문서 송신 경로**이므로 복수 파일 한 메일 송신을 지원한다고 가정하지 않는다. 지원 불가하면 새 묶음 승인 인터페이스의 설계/승인을 먼저 받고 구현은 보류.

## 3. 독립 계약 (미구현)

| 객체 | 제안 필드 |
|---|---|
| `OrchestrationRun` | `run_id,user_id,gmail_message_id,gmail_thread_id,request_hash,status,error_code` |
| `DocumentTask` | `run_id,kind,document_id,revision,proposal_id,review_hash,approval_status,source_ids` |
| `AttachmentManifest` | `user_id,file_id,kind,document_id,revision,file_sha256,filename,mime_type,size` |
| `EmailEnvelope` | `to,cc,bcc,subject,body,thread_id,reply_to_message_id,manifest_ids,envelope_sha256,approval_revision` |
| `SendIntent` | `user_id,run_id,envelope_sha256,idempotency_key,status,gmail_sent_message_id` |

상태: `received → classified → needs_input/drafting → awaiting_document_approval → awaiting_email_approval → sending → sent`; 예외 `cancelled,failed,send_unknown`. 체크포인트·상태는 영속 저장을 검토하되 개인 시스템의 메모리 Checkpointer만으로 재시작 복구가 된다고 간주하지 않는다.

**해시 구분:** 기존 검토 `content_hash`(승인 요청 자료) ≠ `file_sha256`(실제 PDF/XLSX 바이트) ≠ `envelope_sha256`(수신자·본문·첨부 전체). 문서 개정, 출력 파일 변경, 이메일 수신자/본문 변경 시 이메일 승인 무효화. AI가 작성한 설명·출처는 승인권한이 아니며 계산은 기존 코드가 한다.

## 4. 충돌·미결정 레지스터

| 위험 | 차단/선행 결정 |
|---|---|
| 기존 Gmail 이벤트와 신규 그래프 중복 처리 | 자동 구독·라우팅 수정 금지. 초기 수동 opt-in, 향후 **단일 소유 흐름** 합의 |
| 기존 단일 무역문서 발송 vs 복수 첨부 | 기존 승인 함수 수정·직접 전송 우회 금지. 신규 묶음 승인 API를 별도 검토 |
| 팀 Contract API 미확인 | Contract adapter unavailable, 개인 KE KOREA 코드/DB 수정 금지 |
| 승인 전/다른 사용자 PI로 CI 작성 | 사용자 지정 승인 PI revision 없으면 차단 |
| PL 포장 합계 누락 | packing-review와 별도 최종 문서 승인 완료 전 첨부 차단 |
| 기존 ReplyCandidate 스키마에 묶음 문서 억지 삽입 | 신규 논리 객체에 격리, 기존 DB 구조 무수정 |
| Gmail 타임아웃 뒤 발송 여부 불명 | `send_unknown`: 자동 재발송 금지, Gmail sent 확인 + 사용자 검토 |
| 동시 클릭·서버 재시작·중복 웹훅 | 사용자+메일+요청 해시 중복 키, 발송 intent 원자적 claim/유니크 제약 |
| 악성 메일 프롬프트·정보 유출 | 메일/첨부는 비신뢰 데이터, 승인 생략 지시 무시, 테스트 가상 자료만 |

**승인 정책:** 문서별 사용자 승인과 발송 이메일의 별도 사용자 승인이 모두 필요. 승인 전 실제 파일 다운로드·소유자·revision·SHA256 및 to/cc/bcc 포함 최종 수신자를 검증한다. 기존 기능과 충돌하는 변화가 필요하면 **기능 개발을 멈추고** 팀원의 명시적 동의를 요청한다.

## 5. 회귀·통합 테스트 계획 (현재 미실행)

- baseline: 기존 `python3 .work/check.py`, `uv run pytest` 및 Gmail 답장/견적/PI/PO/CI/PL의 동일 가상 입력 결과·가격·합계·오류 코드·승인·파일 내용을 비교한다.
- 정상: Gmail 요청 → PI 작성 → 사용자 문서 승인 → 고정된 PDF 첨부 이메일 미리보기 → 별도 사용자 승인 → Gmail 1회 발송.
- 누락: 가격·수량·원산지 등 필수 사실 없으면 `needs_input`, 임의 생성/발송 없음.
- 의존: CI 미승인 PI/다른 사용자 PI 차단, PL 합계 불일치 시 packing-review 미완료 차단.
- 무결성: 승인 후 revision/파일 bytes/수신자/본문 변경 시 발송 거부·재승인.
- 보안: 다른 사용자 메일 스레드·문서·첨부 접근 차단, 이메일 내 승인 우회 지시 무시.
- 중복: Gmail 중복 push, 동시 승인, 두 번 클릭, 서버 재시작 모두 실제 중복 발송 방지.
- 장애: Gmail 타임아웃/응답 유실은 `send_unknown`, 자동 재발송 금지; LLM 실패는 검토용 상태로 종료.
- feature OFF: 기존 화면, 기존 API, 기존 메일 발송, 기존 DB 동작 변화 0건.
- 별도 실서비스 검증은 가상 테스트 계정으로 수행. 자동테스트 통과 ≠ 실제 Gmail/Render 검증 완료.

## 6. Writing-plans — 추후 **별도 승인 후** 1절 = 1 Issue/PR

> 다음 절은 작업 계획 **제안**이지 지금 코드를 구현하라는 허가가 아니다. 서로 다른 절을 한 PR로 묶지 않는다. 팀 `AGENTS.md`, `.work/RULES.md` 7절과 공통 부분 조율 규칙을 우선한다.

## 1. 기준선·변경 금지 계약 문서화
- 할 일: 현재 main의 Gmail·Trade·Review·Approval API/테스트/입출력 결과를 기준선으로 확정한다.
- 완료 기준: 정상/실패 fixture, 기존 기능 비교표, 위험·불변 파일 목록 승인.
- 영향받는 상태·도구·노드: 기존 Gmail/Trade 관련 파일 읽기 전용.
- 섞지 않을 것: 신규 코드, 기존 코드 변경, Gmail 자동 라우팅.
- 선행 작업: 없음.
- 하는 사람: Codex.

## 2. 신규 오케스트레이션 상태·API·승인 계약 확정
- 할 일: 본 README의 새 객체·상태전이·권한·hash·중복 제어 계약과 보존 기간을 확정한다.
- 완료 기준: 입력/출력/오류·승인·스레드 소유권·복구 명세 합의; 기존 AgentState 불변.
- 영향받는 상태·도구·노드: 신규 계약만.
- 섞지 않을 것: 기존 공통 그래프·DB 변경, Gmail 발송.
- 선행 작업: 1.
- 하는 사람: Codex.

## 3. Master LangGraph opt-in 분류 경로
- 할 일: 별도 graph/state/router/checkpointer와 feature OFF 기본값의 수동 진입점 구현.
- 완료 기준: 기존 실행 결과 불변; 요청 분류 정확성/누락/중복 테스트 통과.
- 영향받는 상태·도구·노드: 신규 orchestration 모듈만.
- 섞지 않을 것: 기존 app/graph·gmail_push 수정, 송신.
- 선행 작업: 2.
- 하는 사람: Codex.

## 4. PI/PO/CI/PL 기존 API 어댑터
- 할 일: 기존 문서 업무 API를 통해 작성·검토·취소·승인하고 PI→CI/PL 선행 관계를 추적한다.
- 완료 기준: 기존 문서 계산·파일·revision 무변경, 권한/오류/경합 회귀 테스트.
- 영향받는 상태·도구·노드: 신규 adapters·DocumentTask.
- 섞지 않을 것: app/trade 수정, 계약서 이식, 메일 송신.
- 선행 작업: 3.
- 하는 사람: Codex.

## 5. 계약서 통합 가능성만 조사
- 할 일: Contract API/인증·승인·version 계약 존재 여부를 문서로 판단하고 연결방안 제안.
- 완료 기준: 없는 API를 있는 척하지 않음, 개인 저장소·기밀 데이터 변경 0건.
- 영향받는 상태·도구·노드: ContractAdapter 설계 문서만.
- 섞지 않을 것: 계약서 엔진/개인 저장소 구현·데이터 연결.
- 선행 작업: 2.
- 하는 사람: Codex.

## 6. 승인 첨부 manifest·메일 미리보기
- 할 일: 승인 파일 소유자/revision/실제 파일 hash, 수신자·본문·첨부 묶음의 승인 전 잠금 모델 설계·구현.
- 완료 기준: 변경된 첨부·수신자·revision은 항상 새 승인 요구. Gmail 호출 0건.
- 영향받는 상태·도구·노드: 신규 AttachmentManifest·EmailEnvelope.
- 섞지 않을 것: 기존 파일 수정, Gmail 발송.
- 선행 작업: 4 (계약 첨부까지 포함하려면 5 추가).
- 하는 사람: Codex.

## 7. 별도 최종 메일 승인·발송 안전장치
- 할 일: 기존 공개 approval 경로의 복수 첨부 지원 여부 검증 후, 지원 불가 시 새로운 승인 API의 **설계 합의부터** 진행. send_unknown/멱등 상태를 구현한다.
- 완료 기준: 무단·중복 발송 0건, 실패·타임아웃·동시 클릭 테스트, Gmail 송신 우회 없음.
- 영향받는 상태·도구·노드: 신규 approval gate/SendIntent.
- 섞지 않을 것: 기존 approval.py·send_email.py 수정, 무승인 전송.
- 선행 작업: 6.
- 하는 사람: Codex.

## 8. 통합 실험·실계정 활성화 여부 결정
- 할 일: 테스트 메일/가상 거래처로 전체 시나리오·성능·보안·복구 확인 후 팀과 자동 수신 소유권 정책 협의.
- 완료 기준: 기존 회귀 전부 통과, 승인 없이 발송 0건, 중복 발송 0건, 사용자가 opt-in 활성화 승인.
- 영향받는 상태·도구·노드: 신규 기능 플래그·배포 정책만.
- 섞지 않을 것: 기존 노드/스키마 변경, 전체 사용자 무단 활성화.
- 선행 작업: 7.
- 하는 사람: 사람(실계정/배포 승인) + Codex(검증 문서).

## 7. 팀이 결정할 미확정 사항

1. 팀 계약서 엔진을 별도로 만들지, 인증된 외부 계약 서비스 API를 정식 연결할지.
2. 복수 문서를 **한 메일에 묶어서 발송**할지, 우선 문서별 별도 메일만 허용할지.
3. Gmail 메일 처리의 기존/신규 그래프 **단일 소유 라우팅**을 어떻게 결정할지.
4. 내구성 있는 Checkpointer·DB, 개인정보/첨부 보관 기간, 모델에 전달할 데이터 범위.
5. 향후 공개 API에 없는 기능을 발견할 때 **기존 파일 수정 허용 여부**(현재 요청 기준: 허용 안 함).

### 향후 Superpowers/Codex 요청 템플릿

```text
encore-ai-campus/aio-03-p2-team3의 docs/plans/mail-document-orchestration/README.md에서
[N번] 절만 참고해 해당 기능 하나를 설계 검토해줘.
기존 app/graph, app/trade, app/services/approval.py, app/tools/send_email.py,
기존 DB·테스트, 개인 KE_KOREA_CO_LTD는 절대 수정하지 마.
이미 있는 기능은 중복 구현하지 말고 근거를 보고해줘.
기존 API로 구현 불가하면 우회 구현하지 말고 충돌과 선택지를 먼저 보고해줘.
추가 구현은 별도 허락 이후에만 시작해.
```

**이 README의 존재는 구현 승인·배포 승인·계약서 자동 발송 허가를 뜻하지 않는다.**
