# React 무역 문서 API

React 화면·마스터 챗봇을 포함하지 않는 FastAPI 백엔드다. 작성/수정은 일반 업무 함수, 문장 추출은 문서별 LangChain 구조화 호출, 승인·파일 저장은 공통 검토 업무가 처리한다. 승인 API가 메일을 발송하지 않는다.

## 폴더와 책임

```text
app/trade/
├── pi/       # PI 입력·샘플·판매가격·계좌 확인
├── po/       # PO 입력·발행사 구매자 역할·매입가격
├── ci/       # 승인된 PI 버전 선택·가격 보존·선적 정보
├── pl/       # 포장 행·단위별 합계·원본 비교와 명시적 합계 승인
├── common/   # 정확한 숫자·공통 조회/HTTP 흐름·가격 준비·SQL 저장·파일 출력
├── review/   # 불변 최종 제안·승인/취소/수정·발급 파일
└── settings/ # 사용자별 회사·통화별 계좌·단가·직인/로고
```

각 문서는 `models.py`, `operations.py`, `agent.py`, `repository.py`, `router.py`를 가진다. 역할·필수 항목은 `rules.py`, CI 출력 수량 조정은 `ci/rendering.py`에 둔다. 업무는 구체 DB·FastAPI·모델 공급자를 import하지 않고 저장소/추출 함수를 주입받는다. 저장 표는 실제 같은 문서 형식을 공유하며 문서별 저장소가 사용자와 문서 종류 범위를 고정한다. 문서별 DB 서버나 범용 에이전트 기반 클래스는 두지 않는다.

`trade` 바로 아래에는 `__init__.py`만 둔다. 공통 계산·가격·상품 매칭·원문 검증·후처리·PDF/XLSX/HTML 구현과 세션/다운로드 API는 `common/`에 둔다. 네 문서의 PDF 구현 이름은 `common/pdf.py`다. 단가표·거래처·직인 DB 조회는 `settings/repository.py`, 문서 저장은 `common/repository.py`, 검토/파일 저장은 `review/repository.py`가 담당한다.

기존 호환 입구 4개는 제거했다. CI는 `ci/imports.py`, PL은 `pl/packing.py`·`pl/packing_review.py`, 샘플은 `pi/samples.py`를 직접 import한다. 회사·은행 필드 목록은 `settings/models.py`에 둬 저장소끼리 순환 import가 생기지 않게 한다. 기존 메일 서비스·도구·노드·테스트도 같은 실제 구현 경로를 사용한다. 계산·검증·승인·오류 반환·API URL과 DB 형식은 이번 폴더 정리로 변경하지 않는다.

## 연결 준비

1. 로그인은 둘 중 하나다(계약 9.1절 경로 구분).
   - React(Supabase): 변경 없는 요청의 `Authorization: Bearer <Supabase access token>` 헤더만 쓴다. 쿠키·CSRF 토큰은 필요 없고 잘못된 토큰이면 쿠키 세션으로 우회하지 않는다. 서버는 `SUPABASE_URL`의 JWKS로 서명·issuer·audience·만료·UUID subject를 검증해 기존 정수 `user_id`에 매핑한다. 사용자 상태·프로필은 `GET /api/me`(Bearer 전용)로 시작한다.
   - 기존 HTML 화면(전환 기간 legacy): Google 로그인 세션 쿠키를 만들고 `GET /api/session`의 `csrf_token`을 변경 요청의 `X-CSRF-Token`에 담는다. React 요청은 `credentials: 'include'`를 사용한다.
2. `/api/trade/settings` 하위에서 회사·단가·계좌·PNG 직인을 설정한다. 원본 회사의 실제 값은 코드에 들어 있지 않다.
3. 다른 출처의 React는 `FRONTEND_ORIGINS`에 정확한 출처를 쉼표로 구분해 지정한다(Authorization 헤더 허용). 사이트가 달라 `SameSite=None`이 필요하면 HTTPS에서 `SESSION_SAME_SITE=none`을 설정한다. 기본값은 lax다.

정확한 필드와 예시는 `/docs`의 OpenAPI를 기준으로 한다. 금액/수량은 `"10"`, `"8.25"`와 같은 십진수 문자열이다. 부동소수점·음수·무한대·허용 범위를 넘는 값은 거부한다. 서버 계산 결과·가격 인증·승인 상태는 입력으로 받지 않는다.

## 네 문서 공통 경로

`{kind}`는 `pi`, `po`, `ci`, `pl` 중 하나다.

| 요청 | 동작 |
|---|---|
| `POST /api/trade/{kind}` | 구조화 입력으로 작성 |
| `POST /api/trade/{kind}/extract` | 문장 추출 후 같은 업무 규칙으로 작성 |
| `GET /api/trade/{kind}` | 본인 문서 최근 50건 요약 |
| `GET /api/trade/{kind}/{id}` | 문서·편집용 input·revision·누락/오류·대기 제안/발급 파일 |
| `PUT /api/trade/{kind}/{id}` | `{revision, document}`로 전체 입력 수정 |
| `GET /api/trade/{kind}/{id}/versions/{revision}` | 보관한 버전 조회 |
| `POST /api/trade/{kind}/{id}/reviews` | `{revision, formats:["pdf","xlsx"]}`로 최종 검토 제안 |
| `GET /api/trade/{kind}/{id}/reviews/{proposal_id}` | 보관한 제안과 선택 결과 조회 |
| `POST /api/trade/{kind}/{id}/reviews/{proposal_id}/decisions` | 승인·취소·수정 선택 |
| `GET /api/trade/files/{file_id}` | 본인이 승인한 파일 다운로드 |

선택 요청은 `action`, `revision`, 반환받은 `content_hash`가 필요하다. 제안 ID는 URL에 둔다. `modify`에만 새 편집 입력 전체를 `document`로 보낸다. 제안 본문은 화면에 보여 주고 변경하지 않은 서버의 해시를 돌려보낸다.

- `approve`: ready인 현재 버전을 issued로 확정하고 같은 트랜잭션에서 파일을 저장한다. 중복·동시 요청은 같은 파일을 반환한다.
- `cancel`: 제안만 cancelled로 종료한다. 문서 초안은 남고 파일은 발급하지 않는다.
- `modify`: 이전 제안을 superseded/modify로 기록하고 문서를 새 버전으로 만든다. 준비됐으면 새 제안을 반환하고, 미완성이면 DocumentResult(`needs_input`)를 반환한다. 이전 동의는 새 내용에 적용하지 않는다.

문서 수정은 기대 revision과 일치해야 한다. 대기 제안은 무효화하고 과거 승인 파일은 보존한다. 승인한 회사·계좌·이미지는 제안 시점에 고정돼 설정 변경 후에도 같은 파일을 내려받는다. 파일 생성에 실패하면 발급하지 않고 pending/ready를 유지한다.

## 문서별 차이

**PO**: 발행사는 buyer, 공급처는 seller다. 매입 단가를 사용하며 PI의 판매 단가·계좌를 복사하지 않는다. **PI**: 발행사는 seller이며 판매 단가와 통화별 계좌를 적용한다. 사용자 지정 샘플 행은 독립된 수량·0원 단가를 허용한다. AI의 샘플 표시는 원문 근거가 있어야 한다. 통화·상품 변경 시 이전 단가 확인을 재사용하지 않는다.

**CI**는 먼저 승인된 PI를 선택한다. 직접 작성 입력 예시는 다음과 같다.

```json
{
  "source_pi_id": 1,
  "source_revision": 1,
  "document_number": "CI-DEMO",
  "shipment_reference": "SHIP-DEMO",
  "country_of_origin": "Republic of Korea"
}
```

`/ci/extract`는 `text`와 사용자 선택 `source_pi_id`, `source_revision`을 받는다. AI가 원본을 선택하지 않는다. 품목·통화·당사자·거래가격·할인·무상 수량은 해당 PI 버전에서만 가져오고 현재 단가표를 적용하지 않는다. 은행·결제 정보를 출력하지 않으며 FOC를 한 번만 표시한다. 다른 PI 버전으로 바꾸려면 새 CI를 만든다. 과거 메일 경로 CI는 원본 PI 연결이 없을 수 있어 조회 시 선택 필요를 안내하고, 원본을 선택해 새 버전으로 보완한다.

**PL**은 가격 대신 포장 행과 원본 합계를 받는다. 최종 검토 전에 다음 절차가 추가된다.

1. `GET /api/trade/pl/{id}/packing-review`에서 원본·행 계산·차이·단위별 수량을 확인한다.
2. `POST …/packing-review/decisions`에 `action:approve|cancel`, `revision`, `content_hash`를 보낸다.
3. 합계 승인 뒤 반환된 새 revision으로 공통 최종 검토를 요청한다.

합계 승인은 계산 가능한 값만 적용하고 원본은 보관한다. PCS와 KG는 각각 표시하고 컨테이너 개수와 FT 규격은 곱하지 않는다. 잘못된 행은 합계 승인으로 덮어쓸 수 없다. 합계 취소는 원본으로 돌아가고, 문서 수정은 합계를 다시 확인하게 한다. 합계 승인과 최종 파일 발급 승인은 별개다.

## 결과와 오류

- `needs_input`: 부족한 정보를 보완하거나 PL 합계를 확인할 정상 경로다. 입력 초안과 revision은 저장된다.
- `ready`: 최종 검토 제안을 만들 수 있는 문서다.
- `issued`: 특정 버전의 파일을 발급했다. 이후 수정은 새 버전으로 처리한다.
- 401 로그인 필요·Bearer 토큰 거부, 403 CSRF 토큰 오류, 404 본인 범위에서 찾을 수 없음, 409 오래된 버전/처리된 제안/업무 선행 조건, 422 입력·출력 형식 오류, 503 AI 추출 실패·로그인 서버 장애다.

업무 오류 본문은 `{"error":{"code":"REVISION_CONFLICT","message":"최신 문서를 다시 확인하세요"}}` 형식이고 Bearer 인증 오류도 같은 형식이다(`invalid_token` 401, `auth_unavailable`/`auth_not_configured` 503). FastAPI 입력 형식 오류와 CSRF 토큰 오류는 기본 `detail` 형식이다. 승인되지 않은 파일이나 다른 사용자의 자료는 내려받을 수 없다.

## 검증

`uv run pytest`는 기존 Gmail·국내 견적·원본 계산/출력 회귀와 새 도메인/ASGI 흐름을 함께 검증한다. 임시 실제 PostgreSQL은 `uv run --with pgserver==0.1.4 pytest tests/test_trade_postgres.py`로 별도 확인한다. 테스트 모델은 가짜 응답이며 실제 Gemini/Gmail·운영 DB·Render를 사용하지 않는다.
