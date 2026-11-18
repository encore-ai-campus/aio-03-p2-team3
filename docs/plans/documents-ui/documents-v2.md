# 문서함 v2 — 생성된 문서·업로드된 문서 (계획)

작성: 2026-11-18 · 상태: 요청자 확인 대기 (PR 미오픈)
요청: v1 복잡 시안 반려 → 단순 목록형. **작업을 나누지 않고 한 번에(단일 PR)**, 클린코드 기준으로 최소 변경.

## 0. 확정된 결정

- 문서함(`/app/documents`)을 **탭 2개**로: ① 생성된 문서(본인 PI·PO·CI·PL) ② 업로드된 문서(지식 문서)
- 목록은 **해당 문서의 메타데이터만** 보여 준다. 소유자 칸·표시 없음(어차피 본인 문서만 조회됨)
- v1의 상태 침 5개·처리 단계 스테퍼·배너·목록/상세 2단 상시 노출은 폐기
- 행 클릭은 기존 화면으로 이동(새 상세 화면을 만들지 않는다)
- 업로드된 문서의 원문 대조·수정·확정 흐름은 그대로 유지(필수 워크플로우)

## 1. 코드 실태 (계획의 근거, 2026-11-18 조사)

| 무엇 | 사실 |
|---|---|
| 무역 문서 목록 API | **이미 존재** — `app/trade/common/router.py`의 `document_router()` 공장이 4종 모두 `GET /api/trade/{pi\|po\|ci\|pl}` → `list[DocumentSummary]` 등록. 소유권 필터·최신 본·50건 (`common/repository.py list()`) |
| DocumentSummary | `document_id, document_type, document_number, doc_no, revision, status, currency, total` — **거래처·수정일 없음** |
| list() 반환값 | 문서 최신 payload 전체(`row.draft` = buyer/seller `Party` 등 공통 모델 포함)를 반환하고 response_model이 요약으로 필터링 → **요약 모델에 필드만 더하면 메타데이터가 붙는다** (쿼리 변경 불필요) |
| 지식 문서 목록 | `GET /api/knowledge/documents` — filename·status·size·created_at·updated_at 등 이미 충분. **변경 불필요** |
| 프런트 | `/app/documents` = `frontend/src/knowledge/KnowledgePage.jsx`(업로드 폼+목록+상세 통합). 처리 중 2초 폴링, 대조·확정 UI 구비 |

## 2. 아키텍처 원칙 (클린코드 적용)

- **도메인 결합 금지**: 생성된 문서 탭은 무역 4종 API를 **프런트에서 병렬 조회해 조합**한다. 무역↔지식을 묶는 크로스 도메인 aggregation 엔드포인트는 만들지 않는다(양쪽 도메인이 서로를 모르게 유지).
- **한 곳에서 한 번**: 4종이 공유하는 요약 모델(`app/trade/common/models.py DocumentSummary`)과 거래처 표시 이름 헬퍼는 common에 **하나만** 둔다. 도메인별 복제 금지.
- **기존 층 유지**: router(얇게) → operations → repository 구조·기존 컴포넌트·토큰을 그대로 쓴다. 새 레이어·추상화·래퍼 추가 없음.
- **가장 짧은 diff**: 백엔드는 요약 필드 확장 한 곳. 프런트는 탭 셸 + 표 + 정규화 훅만 새로 만들고, 업로드 상세·대조 흐름은 한 줄도 안 고친다.
- 쓰지 않는 것(안 만듦): 상태 필터 칩, 정렬 옵션, 페이지네이션 UI, 파일 칸(행 클릭→기존 문서 화면에 다운로드 있음), 소유자 칸, "나중에 쓸지도" 코드.

## 3. 변경 계획

### 3.1 백엔드 (파일 2개, 최소)

1. `app/trade/common/models.py`
   - `DocumentSummary`에 `counterparty: str | None`, `updated_at: str | None` 추가
   - 같은 파일(또는 common 내 인접 위치)에 거래처 표시 이름 헬퍼 1개: `buyer.name`/`seller.name` 중 문서 종류에 맞는 쪽(PI·CI·PL→buyer, PO→seller. 구현 첫 단계에 각 문서 payload로 확인)
2. `app/trade/common/router.py` — 목록 엔드포인트의 매핑에서 새 필드 채우기 (snapshot에 이미 있는 값에서)

지식 문서 쪽 백엔드 변경 **없음**.

### 3.2 프런트 (신규 `frontend/src/documents/` + 기존 파일 소폭)

```
frontend/src/documents/
  DocumentsPage.jsx     — 탭 셸(?tab=issued|uploaded URL 동기화) + 이름 검색
  IssuedDocuments.jsx   — 생성된 문서 표 (순수 표시, 행 데이터·클릭 콜백 props)
  useIssuedDocuments.js — 4종 병렬 fetch(Promise.all) + AbortController 정리 + 정규화 mapper
  documents.css         — 화면 전용 스타일(다른 화면과 안 겹치는 prefix)
```

- 라우트: `/app/documents`가 `DocumentsPage`를 향하게 `App.jsx` 한 줄 수정. `?tab=uploaded&document={id}`면 기존 `KnowledgePage` 상세를 그 아래(또는 전환)에 렌더 — **기존 KnowledgePage의 대조·확정 코드는 재사용하고 목록 부만 새 표로 대체**
- 파생 값(검색 필터·개수·합친 최신순)은 렌더 중 계산 — 상태/이펙트로 파생state 만들지 않음
- 업로드 탭의 처리 중 폴링은 기존 KnowledgePage 규칙 그대로 유지
- 상태: 로딩=실제 크기 회색 바, 오류=블록 안 문장+재시도, 빈=문장("생성된 문서가 없습니다" / 문서함 첫 화면 안내)

### 3.3 화면 명세 (메타데이터 칸)

**① 생성된 문서** — 행 클릭 → `/app/trade/{kind}/{id}` (기존 화면)

| 종류 | 문서번호 | 거래처 | 상태 | 총액 | 수정일 |
|---|---|---|---|---|---|
| PI | PI-2026-1102 | Global Trade Co. | 발급 | USD 12,400 | 11-18 |
| CI | CI-2026-0031 | Global Trade Co. | 검토 | USD 12,400 | 11-17 |

- 종류 배지(PI/PO/CI/PL)·상태(초안/검토/승인/발급)는 기존 상태 어휘 그대로 알약으로
- 총액은 `total` + `currency` (없으면 회색 대시)

**② 업로드된 문서** — 행 클릭 → 기존 상세(원본 대조·확정)

| 파일명 | 형식 | 상태 | 페이지 | 크기 | 올린 날짜 |
|---|---|---|---|---|---|
| 거래처별 단가표.xlsx | XLSX | 확인 필요 | 12 | 2.4MB | 11-18 |

공통: 제목줄 "문서함" + 오른쪽 업로드 버튼(업로드 탭에서만 활성) / 이름 검색 1개

### 3.4 시안

구현 전 **단순 시안 1장**(지금까지 방향: 참고 스크린샷 스타일 재첨부받으면 그대로 반영)을 `docs/plans/documents-ui/`에 만들어 확인받는다. v1 시안(`문서함-개편-시안.html`)·현재 화면 복제본(`문서함-현재-복제.html`)은 참고 이력로 유지.

## 4. 테스트·검증

- 백엔드: 기존 무역 목록 테스트 패턴에 새 요약 필드 2개 단언 추가(소유권 분리·최신 본 회귀 유지)
- 프런트: 정규화 mapper 테스트 1개 파일(4종 응답 → 표 행, 빈/실패 정합성) — 기존 `npm test` 패턴
- 확인: `npm run lint`·`npm test`·`npm run build`·`python3 .work/check.py` (+ `uv run pytest`는 CI에 위임)
- 브라우저 확인은 요청자가 직접(기존 규칙)

## 5. 순서 (단일 PR 안에서)

1. 백엔드 요약 필드 확장 + 테스트 (거래처 필드명 확인 포함)
2. 프런트 documents 모듈 + KnowledgePage 연결
3. 시안 확정 스타일 반영
4. lint·test·build + 규칙 검사
5. `docs/PROJECT_CONTEXT.md` 2절(문서함) 갱신 + 이 계획 완료 표시

## 6. 섞지 않을 것

- 원문 대조·확정 플로우 변경, RAG 검색 연결, 문서 삭제 API
- 메일함·작업현황 화면, 앱 공통 `styles.css`(버튼 리셋 등 공통 스타일은 손대지 않음 — #236 경험)
- 백엔드 무역 도메인 로직(계산·검토·승인) — 요약 필드만

## 7. 확인 필요 (요청자)

1. **참고 스크린샷 재첨부** — "이런 방식"의 정확한 스타일(칸 구성·행 모양)을 아직 못 봄. 시안에 그대로 반영
2. **생성된 문서 범위** — 초안·검토 중 포함 "전 상태"로 계획함(상태 칸으로 구분). 발급 완료만 원하면 필터 한 줄로 좁힘
3. 총액·거래처는 문서 종류별로 항상 있지 않을 수 있음(초안) — 없는 칸은 회색 대시로 표시하는 것으로 계획함
