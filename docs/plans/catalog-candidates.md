# catalog-candidates 계획

- 목표: 별칭 사전 없이 한·영 혼용 품목 입력을 해석하되, LLM은 **현재 사용자가 볼 권한이 있는 카탈로그의 실제 ID만** 후보로 돌려주고, 최종 품목은 사용자가 행마다 명시적으로 고르게 한다. 이 문서는 [llm-quality-and-cost.md](llm-quality-and-cost.md) 3절을 바꾸지 않고 그 계약·검증 방법을 구체화한다.
- 관련 요구사항: R-03(추가 확인, llm-quality-and-cost.md 기준), R-09·R-10(오류/재검증)
- 관련 Issue: 없음
- 조율함: 공통 LLM client/config/PC worker/기한은 모델 프로필 작업(llm-quality-and-cost.md 4절, 별도 세션)이 소유하고 이 기능은 그 계약의 소비자다. 계약 초안 [llm-model-profiles.md](llm-model-profiles.md)(draft_not_adopted)을 같은 PR에서 받아 1.6을 맞췄다. 계약 확정·김민성 조율은 남았다.
- 상태(2026-11-18): **준비 단계.** 운영 코드·PR·push·유료 호출 없음. 운영 구현은 3절의 선행 조건이 모두 갖춰진 뒤에만 한다.
- 태그: [Request] 요청자 지시 · [Past work: 파일] 기존 문서/코드에서 가져옴 · [Claude proposal] 이 문서의 제안(요청자 확인 전)

## 0. 현재 사실 (구현 / 실측 / 미확인)

| 구분 | 내용 |
|---|---|
| 구현됨(main 428139a 확인) | 후보 검색은 개인 단가표만 읽는다: `GET /api/trade/settings/products/search`(역할 sale/purchase 필터)가 `search_products`로 문자열·오타 검색. 프런트 `ProductCandidates.jsx`가 250ms 뒤 자동 호출하고 `product-selection.js`의 `selectProduct`가 품목명·코드·규격만 행에 넣고 단가 사용 확인(`confirm_price_override`)을 false로 되돌린다. 공유 카탈로그(`aio3_catalog_*`)를 읽는 코드는 없다. |
| 이 브랜치에서 준비 | 3절 계약의 실행 가능한 기준 구현과 모의 시험(2절). 운영 앱 코드는 바뀌지 않았다. |
| 실측 | 공유 SKU 49개 수신, 사람이 확인한 정답 10개(`catalog-query-confirmed.json`). PC 선별 40회(Luna medium 3회 반복 30·Sol medium 10, 2026-11-18): 자동 정답 대조 30/30·10/10, 시간 초과·비용 미상 0건, 추계 USD 0.0979. 질의 10개·SKU 49개 선별이라 **품질 게이트 통과가 아니다**([llm-quality-and-cost.md](llm-quality-and-cost.md)). 앱 JWT 인증·서버의 현재 권한/버전 재검증은 확인된 적 없음. |
| 미확인 | 앱이 쓰는 Supabase 인증 프로젝트와 공유 카탈로그 프로젝트가 같은지, 공유 카탈로그를 앱 서버가 읽을 경로(4절 결정 1), 모델 품질·지연·실제 청구, 모델 프로필 계약의 필드/기한, PC worker 지원. |

기존 `SEARCH_TERMS`(슈퍼라이트→superlight 등 발음 치환표)는 별칭표다. 이 기능은 그 표를 늘리거나 재사용하지 않고, 일부 한글이 맞는다는 이유로 다국어 지원이라 표현하지 않는다. [Request]

## 1. 계약 (이 문서가 확정하는 것)

- 할 일: 아래 1.1~1.10을 계약으로 고정한다. 기준 구현 `tests/fakes/catalog_candidates_reference.py`가 같은 오류 코드와 순서를 따른다.
- 완료 기준: 2절의 모의 시험이 통과하고, 모델 프로필 담당과 1.6의 소비 항목이 맞춰진다(맞춰지기 전에는 이 절을 '확정'으로 표시하지 않는다).
- 영향받는 상태·도구·노드: 새 API 두 개와 어댑터(3절에서 구현). 그래프 상태·도구 스키마(공통 부분)는 바꾸지 않는다.
- 섞지 않을 것: 별칭/음역 사전, 가격·단가·승인·발송 권한, 공통 모델 설정/워커/재시도 체계의 중복 구현, 후보 검색 UI 개편.
- 선행 작업: 없음(문서).
- 하는 사람: Claude(작성) / 요청자(4절 결정)

### 1.1 소유 경계
| 항목 | 소유 |
|---|---|
| 카탈로그 범위 조회, ID·회원·버전 검증, 후보 API/UI, 행별 최종 선택 | 이 기능 [Request] |
| 모델·effort·timeout·출력 상한·키/실행 모드·PC 큐/임대/heartbeat·HTTP·프런트 기한 | 모델 프로필 작업. 이 기능은 `catalog_candidates` 프로필을 읽기만 한다 [Request] |
| 단가 검증·PL 합계·문서 승인·메일 발송·사용자 소유권/키 격리 | 기존 경로 그대로. 후보 선택은 이 중 어느 것의 권한도 아니다 [Request] |

### 1.2 범위(scope)와 ID
- 범위 ID는 서버가 부여한 문자열이다: `personal:sale`, `personal:purchase`(본인 `price_list_items`, ID는 행 id), `shared:<카탈로그>`(공유 카탈로그, ID는 `sku`). 서로 다른 범위의 ID는 섞거나 합치지 않고, 영수증에는 항상 범위를 함께 적는다. [Request: 공유 SKU와 개인 단가표 id 구분]
- 클라이언트가 범위를 고를 수는 있지만 서버가 **그 요청 시점의 현재 권한**으로 허용 목록을 다시 만든다. 허용 범위가 둘 이상이면 `scope_id`가 필요하다(추측해서 고르거나 합치지 않음). [Claude proposal]
- 공유 범위의 권한은 reader 회원 확인(`aio3_catalog_members.user_id` = 로그인 사용자의 Supabase UUID)으로만 인정한다. 개인 단가표 소유와 구분한다. [Request]

### 1.3 카탈로그 버전
- `catalog_version = sha256(canonical({범위 ID, 모델 필드만 담은 항목들을 ID 순으로}))`. 모델 필드: `id, item_name, brand, source_code, color, switch_type, capacity, unit`. 가격·별칭·재고·카테고리·연락처는 입력에도 버전에도 넣지 않는다. [Claude proposal; 필드는 Past work: SESSION_HANDOFF 모델 자료 범위]
- 항목 순서나 가격만 바뀌면 버전은 그대로, 이름·규격·ID·항목 수가 바뀌면 달라진다. 중복 ID는 `catalog_invalid`.
- 공유 카탈로그 쪽 export 해시(`ab3664…`)와 같은 알고리즘이라고 가정하지 않는다. 서버가 후보 생성 때 읽은 바로 그 데이터로 계산한다.

### 1.4 API (요청 본문에 사용자·버전·권한을 싣지 않는다)
| 호출 | 본문 | 서버 결정 |
|---|---|---|
| `POST …/catalog-candidates/find` ('AI 후보 찾기' 버튼에서만) | `query`(1~200자), `row_id`, `scope_id`(선택) | 사용자(인증), 허용 범위, 카탈로그 읽기/버전, 문서 행 출처 해시 |
| `POST …/catalog-candidates/select` (후보 버튼 클릭) | `candidate_set_id`, `row_id`, `selected_id` | 세트 소유자·행·유효기간·범위·버전·항목 존재 |
| `POST …/catalog-candidates/cancel` | `candidate_set_id`, `row_id` | 미확인 유지 |

`user_id`·`catalog_version`·`role`·가격 등은 보내면 거부(`forbidden_client_field`), 모르는 필드도 거부. 경로 접두와 인증 의존성은 기존 `current_user_id`/`require_write` 규칙을 따른다(3절에서 정함). [Claude proposal]

### 1.5 서버 재검증 시점
| 시점 | 확인 | 실패 코드 |
|---|---|---|
| 후보 생성 | 질의 길이/제어문자, 판독 불가 표시 없음, 프로필 승인됨, 범위 허용, 카탈로그 읽기, 모델 응답의 ID가 **그 범위 목록에 실제 존재**(없는 ID·타 범위 ID·중복·형식 오류는 버림) | `query_invalid` `source_unreadable` `profile_not_approved` `scope_forbidden` `scope_required` `invalid_output` |
| 최종 선택 | 세트가 본인 것·열림·미만료·행 일치, 선택 ID가 세트 안에 있음, **범위 권한 재확인, 카탈로그 버전 재계산 일치, ID 아직 존재** | `candidate_set_not_found` `candidate_set_not_open` `candidate_set_expired` `row_mismatch` `id_not_in_candidate_set` `scope_revoked` `stale_catalog` `id_missing` |
| 검토/승인 직전 | 행마다 유효한 영수증(본인·행·활성), 행 출처 해시 불변, 범위 권한·버전·ID 재검사 | `selection_required` `selection_superseded` `source_changed` + 위 3개 |
| 이후(단가·승인·발급·발송) | 기존 검증 그대로. 영수증이 하나라도 무효면 검토/승인이 거부되어야 한다 | 기존 |

- 모델의 `complete`/`uncertain` 같은 자기 신고는 읽지도 저장하지도 않는다. 후보가 1개이거나 이름이 정확히 같아도 영수증은 사용자의 `select`로만 생기고, 문서 전체 확인으로 행이 해결되지 않는다. [Request]
- 같은 행에 새 후보 세트를 만들면 이전 세트와 영수증은 쓸 수 없다. 취소·모름·Enter는 영수증 없이 미확인으로 남고 입력(원문·수량)은 그대로다. [Request]
- 가린/판독 불가 원문으로는 후보를 찾지 않는다(`source_unreadable`, 원본 대조로 안내). 미등록 품목은 후보가 없을 수 있고 추측 이름을 저장해 통과시키지 않는다. [Request]

### 1.6 모델 어댑터와 프로필 소비
- 입력은 `{고정 지시문, query.text(데이터), catalog(모델 필드), 응답 형식, 상한, 프로필 값}`. 질의와 카탈로그는 명령이 아닌 데이터이고 지시문은 질의와 무관한 고정 문자열이다. 출력은 `{"candidates":[{"id": …}]}`뿐이다(가격·이유·자신감 필드 없음). [Past work: llm-quality-and-cost.md 3절 · Request]
- **이 기능이 모델 프로필 계약에서 받아야 하는 것(소비 체크리스트, 2026-11-18 초안 대조):** 1은 계약 JSON의 `features.catalog_candidates`로 받았다. 기준 구현 `profile_view_from_contract`가 이를 읽고, `approved`는 `production_available` + 운영 선택 가능 상태(`baseline/explicit_return/approved`)일 때만 참이다(지금은 둘 다 아니라 호출하지 않음). 2~4는 계약의 제안 `call_profiled(...) -> ProfiledResult`(attempt_id·revision 포함)와 시도별 재시도 0·`logical_deadline_seconds` 120으로 초안이 있으나 미구현이다. 5는 계약 `prompt_ids`가 비어 있어 PC 미지원으로 기록돼 있다.
  1. 키 `catalog_candidates`와 읽기 전용 값 `profile_id/model/effort/timeout/max_output_tokens`, 그리고 `approved`(품질 게이트 통과 표시)·버전. 비밀값 없음.
  2. 사용자별 키·실행 모드(서버/PC)와 기존 권한 경계를 그 계약이 적용한 호출기(이 기능은 직접 호출 안 함).
  3. **한 번만 시도하는 호출 모드**: 현재 `app/llm/client.py::call_structured`는 네트워크/timeout에서 최대 2회 재시도(대기 포함)하고 timeout 20초가 고정이다(main 428139a). 이 기능은 timeout 뒤 자동 재요청·다른 모델 호출을 하지 않으므로, 프로필 계약이 재시도 상한과 전체 기한(재시도 합 포함)을 프로필에 담아야 한다.
  4. 시도(attempt) 식별자와 늦은 응답 폐기: 기준 구현은 동기 호출이라 응답이 늦으면 후보·영수증·캐시를 만들지 않는다. 큐/PC 실행에서는 열린 시도 하나만 응답을 받는 fencing과 임대/기한 값이 필요하다.
  5. **PC worker 프로토콜**(main 428139a): 설치된 정의가 13개로 `Capabilities.definitions`의 `max_length=13`이 가득 찼고, `JobRequest`에는 `requested_model`만 있고 effort/timeout/출력 상한 필드가 없으며, 매니페스트는 모델 하나만 허용하고, `variables`는 `str|int`라 카탈로그 목록은 문자열 변수로 직렬화해야 한다(128KiB 상한). 이 기능을 PC 모드에서 쓰려면 세 가지가 프로필 쪽 프로토콜 변경으로 해결돼야 한다. 그 전에는 서버 모드만 대상으로 하고 PC 모드는 `기능 미지원` 안내로 복귀한다.
- 측정 준비값(medium / 90초 / 출력 2048)은 승인된 설정이 아니다. `approved=false`이면 호출하지 않는다. effort `high/xhigh/max`는 어떤 경로로도 호출하지 않는다(심층 방어, 정책 원본은 프로필 계약). 기준·명시적 복귀는 Luna medium, 비교 후보는 Sol medium. [Request]

### 1.7 화면(상태와 행동은 확정, 문구는 요청자가 정함)
- 기존 250ms 자동 검색은 그대로 두고 그 옆에 명시적 **'AI 후보 찾기'** 버튼을 둔다. 입력마다 LLM을 호출하지 않는다. [Request]
- 후보는 품목명·코드·규격과 범위를 보여 주고, 사용자가 후보 버튼을 눌러야 그 행의 `product_name/product_code/capacity`가 채워진다. 단가는 채우지 않고 기존 단가 확인(`confirm_price_override=false`)과 기존 가격 확인 흐름을 그대로 탄다. 공유 SKU 선택이 개인 단가표 가격과 어떻게 이어지는지는 3절 구현 때 확인하며, 연결이 없으면 지금처럼 단가를 직접 입력/확인한다(**미확인**).
- 후보가 없을 때, 후보가 여럿일 때(색상·세대·변형 모호), 오류·시간 초과·한도·미지원일 때 모두 원문과 수량·기존 입력을 보존하고 기존 검색/직접 입력으로 돌아갈 수 있어야 한다. 가린 원문 행은 버튼을 비활성화하고 원본 대조를 안내한다.
- 필수 한계 문구(이 기능이 MVP에 없거나 품질 기준 미달일 때): “현재 자동 품목 검색은 영어 제품명 부분검색·오타검색 기준입니다. 다국어 자동 연결은 지원하지 않습니다.” 다국어 AI가 일시 실패하면 영어 재검색/직접 선택을 안내한다. [Past work: llm-quality-and-cost.md 3절 · Request] 그 외 버튼·상태 문구는 요청자 결정이다(RULES 1절).

### 1.8 실패와 복귀
- 키/예산/시간/모델 오류 → 원문·수량 보존, 기존 후보/직접 선택. 기본 복귀는 **명시적인 기존 프로필(Luna medium) 선택**이고 자동 fallback은 없다. timeout은 공급자가 이미 처리했을 수 있어 자동 재요청하지 않는다. [Past work: llm-quality-and-cost.md 3·4절]
- 설정 변경은 새 시도에만 적용하고 이미 발급한 파일·이전 처리 결과·이전 영수증의 의미를 바꾸지 않는다. 승인·발급·메일 발송을 재생하지 않는다. [Request]

### 1.9 호출 한도와 캐시 (잠정값, 측정 뒤 확정) [Claude proposal]
- 캐시 키 `(사용자, 범위, 카탈로그 버전, 정규화 질의 해시, 프로필 ID)`. 같은 키는 모델을 다시 부르지 않고 새 후보 세트만 발급하며, 카탈로그 버전·프로필이 바뀌면 무효다. 사용자별 창당 실제 모델 호출 수를 제한한다(기준 구현 기본 5회/60초). 후보 최대 10개, 세트 유효 15분.
- 전체 카탈로그를 매번 통째로 보내는 구현은 49개~200개 규모에서만 쓴다(기존 측정기도 200개 상한). 더 큰 카탈로그는 의미/분할 검색의 후보 재현율을 먼저 별도로 측정해야 하고 이 계약은 그 설계를 포함하지 않는다. [Past work: llm-quality-and-cost.md 3절]

### 1.10 하지 않는 것
가격·추측 ID·외부 제품 생성, 별칭/음역 사전, 클라이언트가 보낸 사용자 ID/버전 신뢰, 후보 1개/이름 일치/`complete=true`로 자동 확정, 문서 전체 확인으로 행 해결, 설정 변경으로 기존 결과 소급 변경, 운영 모델 기본값 변경, Codex/이 환경의 유료 호출·키 요청.

## 2. 모의 검증 (준비 완료 범위)

- 할 일: 계약을 가짜 카탈로그·가짜 모델로 실행해 본다.
- 완료 기준: `tests/test_catalog_candidates_contract.py`의 20개(프로필 계약 소비 2개 포함)가 통과(2026-11-18 클라우드 작업공간에서 이 파일만 실행). 확인된 10질의 × 실제 공유 SKU 49개 시험은 기록 폴더(`CATALOG_RECORDS_DIR`)가 있을 때만 돈다. 계약을 일부러 깬 변형 5개로 시험이 실패하는 것도 확인했다.
- 영향받는 상태·도구·노드: `tests/`만. 앱 코드·DB·네트워크·LLM 호출 없음.
- 섞지 않을 것: 모델 품질 판정(가짜 모델이 정답을 말하게 한 것이므로 품질 근거가 아님), 앱 인증/DB 통합 통과 표시, 전체 테스트 반복.
- 선행 작업: 1절
- 하는 사람: Claude

시험이 다루는 것: 모델 입력에 가격/별칭 없음·질의는 데이터·고정 지시문, 없는/타 범위/중복 ID 제거와 자기 신고 무시, 후보 1개·정확 일치도 자동 확정 없음, 클라이언트 ID/버전 거부, 범위 결정·회원 철회·버전/출처 변경·낡은 세트·다른 사용자/행/ID 거부, 취소 시 미확인 유지·입력 보존, timeout 한 번만 호출·늦은 응답 폐기, 캐시·한도·승인 전 프로필·high effort 차단, 판독 불가 원문, 개인/공유 ID 혼용 방지. 다루지 않는 것: 실제 모델 품질, 실제 DB/RLS/JWT, 프런트 동작, PC worker.

## 3. 운영 구현 (차단됨)

- 할 일: `catalog_candidates` 프로필을 읽는 어댑터, 후보 API 3개, 공유/개인 카탈로그 읽기 포트, 영수증 저장·승인 직전 재검사, 'AI 후보 찾기' UI와 한계 문구, 서버+실제 DB+브라우저 시험.
- 완료 기준: 1절 계약의 모든 오류 코드를 실제 DB로 시험, 타인/철회/버전 변경/직접 API 우회 차단, 후보 1개에서도 사용자 선택 없이는 승인 불가, 실패·취소 시 입력 보존, 복귀 시나리오, `uv run pytest`·`python3 .work/check.py` 통과.
- 영향받는 상태·도구·노드: `app/trade/…`의 후보 API·영수증 표(새 DB 표 필요 시 migration), `frontend/src/trade/ProductCandidates.jsx`와 선택 로직, 승인 직전 검사 지점. 공통 부분(그래프 상태·도구 스키마) 변경이 필요하면 담당자와 조율한다.
- 섞지 않을 것: 공통 모델 설정·워커·기한(프로필 작업), 가격·승인·발송 변경, SKU 회원 검색 자체의 다른 기능.
- 선행 작업: **(a)** 관련 품질 근거(카탈로그 유료 비교 결과와 대표 자료 10건+·조건당 3회 게이트 통과, 현재 0회), **(b)** 모델 프로필 계약 확정과 1.6 체크리스트 충족, **(c)** 4절 결정 1. 하나라도 없으면 이 절을 시작하지 않는다.
- 하는 사람: Codex(선행 조건 충족 뒤)

## 4. 열린 결정·미확인

1. **공유 카탈로그를 앱 서버가 읽는 경로와 사용자 일치 여부 (요청자 결정/확인)** — 앱의 DB(`users`)와 `auth.users`를 쓰는 Supabase 프로젝트가 공유 카탈로그 프로젝트와 같은지에 따라 회원 확인 방법이 달라진다. 같은 프로젝트면 서버가 `users.supabase_uid`로 reader 회원을 조회할 수 있고, 다르면 같은 UUID가 아니므로 회원 연결이 따로 필요하다. 이 계약의 포트(`scopes_for`, `entries`)는 어느 쪽이든 유지된다.
2. 모델 프로필 계약 확정 — 초안은 받았다(1.6). `prompt_ids`·`request_revision`·호출 한도/캐시를 이 기능이 정해 계약에 넣어야 하고, `max_output_tokens`·`logical_deadline_seconds`는 계약에서 미정(unresolved)이다.
3. 화면 문구(1.7의 필수 한계 문구 외), 한도·캐시·후보 수·유효기간 값(1.9 잠정값).
4. 공유 SKU 선택 뒤 단가 처리(개인 단가표 매칭 여부), 대형 카탈로그의 후보 재현율.
