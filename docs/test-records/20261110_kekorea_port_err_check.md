# KE KOREA 이식 KNOWN_ERRORS(ERR) 점검표 — kekorea-port 6절

- 점검일: 2026-11-10 · 점검 사람: Claude(kekorea-port 6절, 연결·회귀 확인)
- 대상: 이식본 `app/trade/*`(·연결 코드) — 기준 문서 `reference/kekorea/KNOWN_ERRORS.md`(2026-11-03, 감사 커밋 `ae4b730` 기록). 원본 사본은 `8d397a1`이라 그 사이 고쳐진 ERR이 섞여 있어(사본 README), **사본(=이식 원본)에서 재현되는지**를 함께 확인했다.
- 방법: `uv run python` 스크립트로 이식 모듈(`match_product`·`verify_item_quotes`·`apply_verified_catalog_prices`·`validate_and_calculate`)을 가상 값(가상 발행 회사 Testworks Trading Co, 가상 상품·코드)으로 직접 호출하고, 매칭 계열(ERR-02·03·09~12)은 사본 `reference/kekorea/Quotation_KEKOREA/agent/product_matching.py`를 `importlib`+`sys.modules` 조작으로 임시 읽어(이식 규칙이 허용하는 읽기 전용 로드, 앱 코드는 import하지 않는다) 같은 입력의 결과를 나란히 비교했다. 사본 진입 필터(`brand == 'ECLADO'`)는 비교 스크립트에서만 키를 넣어 통과시켰다(계약 15.4절이 이식본에서 없앤 필터).
- 판정: **재현됨** = 이식본(및 사본)이 오류 문서의 동작을 그대로 보인다 · **재현 안 됨** = 이식본에서 그 동작이 일어나지 않는다(고쳐졌거나 구조가 다름) · **일부 재현** = 사본 스냅샷에서 일부만 남아 있다.

## 점검 결과

| ERR | 등급·제목 | 이식본 결과 | 근거(실행·코드) |
|---|---|---|---|
| ERR-01 | P1 통화를 바꾸면 이전 카탈로그 단가가 남는다 | **재현됨**(발송 차단은 됨) | 실행: USD 카탈로그 단가 적용(단가 10, `master_price=True`) 뒤 통화를 EUR로 바꾸고 재검증하면 단가 10·`product_id`·출처가 남고 `master_price=False`만 바뀐다(`app/trade/pricing.py` `apply_verified_catalog_prices` — 원본과 같은 자리 수정). 다만 이식본에서는 'Verified EUR catalog price …' 경고가 `missing_fields` → `blocking_issues`(`app/trade/trade_documents.py` `validate_and_calculate`)로 이어져 **발송이 차단**된다(`app/services/trade_docs.py` `finalize_draft` → status `needs_input`). 원본의 "PDF 버튼 활성" 위험(=ERR-05와 결합 부분)은 이식본 발송 조건 구조상 없다. |
| ERR-02 | P1 상품명 소수점이 제거되어 다른 숫자와 일치 | **재현됨**(사본·이식본 일치) | 실행: `COLLAGEN 50.00 SERUM` ↔ 카탈로그 `COLLAGEN 5000 SERUM`, `C.P 5.0` ↔ `C.P 50` 모두 `matched`(추가 확인 없음). `app/trade/product_matching.py`는 사본의 복사본이라 같다. |
| ERR-03 | P1 이름 안의 `.50g`가 `50g`처럼 처리 | **재현됨**(사본·이식본 일치) | 실행: 카탈로그 `Cell Memory Cream / 50g`, 이름 `Cell Memory Cream .50g` + 별도 용량 `50g` → `matched`. |
| ERR-04 | P1 출처에 없는 제품코드가 상품 변형·단가를 결정 | **재현됨**(계약 15.8절: 원본 재현 상태로 유지) | 실행: 원문 `Cream quantity 10 PCS`에 후보 `product_code=SKU-2`, `capacity=null` → `verify_item_quotes`의 충돌에 product_code 항목은 없고(코드 검사 자체가 없음), SKU-2(100ml)로 `product_id`·단가 9·`master_price=True`가 확정된다. |
| ERR-05 | P1 계산·출고 오류와 실제 생성 차단 조건이 다르다 | **재현 안 됨** | 원본의 차단 조건은 화면 코드(`app.py`)에 있었는데 화면은 이식하지 않았다. 이식본은 발송 조건이 `status="ready"`(=`blocking_issues` 전부 비었을 때만, `app/services/trade_docs.py` `finalize_draft`) 하나뿐이고 승인 경로(`app/services/approval.py` `send_approved_trade_document`)가 그것을 검사한다. 단위 불일치·행사 불일치 입력이 blocking으로 나오는 것은 ERR-07 실행에서도 확인했다. |
| ERR-06 | P2 누락 수량 보완 입력 뒤 행사 증정 수량이 재계산되지 않는다 | **재현 안 됨** | 원본 2026-11-03 후속 수정(수량 입력·수정·검증 단계에서 증정/출고 재계산, KNOWN_ERRORS 10절)이 사본 `8d397a1`에 반영돼 있고 이식본도 같다. 실행: 2+1 행사·유상 5 → 증정 2·출고 7로 재계산. 이식본의 보완 경로 `revise_trade_document` → `finalize_draft` → `validate_and_calculate` → `recalculate_order_promotions`가 매번 다시 돈다. |
| ERR-07 | P2 단가 기준의 통화·단위 검증이 일관되지 않는다 | **재현됨** | 실행(원본 표와 같은 4조합): USD/KRW/KG·KG(polysilicon) 오류 없음, `per SET`/KG 오류 없음, USD/W/KG(other) 오류 없음, EUR/EUR/KG/KG → 'Price basis EUR/KG does not match quantity unit KG' 오류. `app/trade/trade_documents.py`의 기준-통화 제거·예외 목록이 원본 그대로다. |
| ERR-08 | P2 관계없는 출처 메모 하나가 회사·거래조건 검증을 우회한다 | **재현됨**(계약 15.8절: 원본 재현 상태로 유지) | 실행: 원문 `Cream quantity 10 PCS`, `source_notes=["Cream"]`(원문에 포함된 짧은 메모)이면 `has_verified_translation_evidence`가 참이 되어 후보의 `Invented Company`·`Invented Address`·`FOB Invented Port`에 대한 당사자·조건 근거 검사가 생략된다(항목 숫자 근거 검사는 그대로 돈다). `app/trade/verify_quotes.py`의 주석도 이 의도를 밝힌다. |
| ERR-09 | P2 잘못된 명시적 코드가 일반 설명으로 남을 수 있다 | **재현됨**(사본·이식본 일치) | 실행: 카탈로그 `Cell Memory Cream / E-165 / 50g`에 `Cell Memory Cream SKU: E165/999`, `Cell Memory Cream SKU: #E999`가 `matched`(추가 확인란 남음 — ERR-02/03과 달리 무확인 확정은 아니다). |
| ERR-10 | P2 동일 용량을 이름에 붙이면 표준 상품이 미인식된다 | **재현됨**(사본·이식본 일치) | 실행: `C.P 50 Ampoule (E-167A-1) 5ml*10pcs`(별도 용량 정확) → `not_found`(곱셈 뒤 `10pcs`가 용량에 섞여 카탈로그와 다르다고 판정). |
| ERR-11 | P2 정상적인 공백·수량 라벨 조합도 일부 실패한다 | **일부 재현**(사본·이식본 일치) | 실행: 2026-11-03 기록의 3케이스 중 `Cell ( SKU: E165 ) Memory Cream`은 사본 스냅샷에서 이미 `matched`로 고쳐져 있었다(감사 뒤 수정). 나머지 `Cell Memory Cream 50g (Qty: 10)`(수량 라벨 제거 뒤 빈 괄호)·`Cell Memory Cream 50g / Item No: E165`(구분용 `/`)은 사본·이식본 모두 `not_found`다. |
| ERR-12 | P2 SPF/PA 상품의 코드 단독 입력은 고유 코드여도 실패한다 | **재현됨**(사본·이식본 일치) | 실행: 카탈로그 `Natural Perfect Sun Cream SPF50+ PA+++`(코드 S-1)에 코드 `S-1` 단독·'등급 없는 이름+코드' 모두 `not_found`(이름의 SPF/PA 등급 비교에서 탈락). |
| ERR-13 | P2 Advanced JSON의 null·목록 당사자가 구조 예외를 일으킨다 | **재현 안 됨**(고침 — 계약 15.8절) | 실행: `validate_and_calculate`에 `buyer=None`·`buyer=[]`를 넣으면 예외 없이 'Buyer legal name is required' 차단으로 처리된다(`party = data.get(role) or {}` 가드). 서비스 층(`app/services/trade_docs.py`)도 초안이 dict가 아닌 경우 승인·취소·수정 대상에서 제외한다. 전용 테스트: `tests/test_trade_counterparties.py` `test_null_or_malformed_party_does_not_crash_instead_of_err13`. |
| ERR-14 | P2 단가 기준(price_basis)이 문서로 전달되지 않는다 | **재현 안 됨** | 원본 감사(2026-11-03) 뒤 사본 `8d397a1`의 `apply_verified_eclado_prices`가 기준 복사를 넣었고(`reference/…/pricing.py` `catalog_basis` 대입) 이식본도 같다. 실행: 기준 없는 품목에 카탈로그 단가(기준 'per PCS')를 적용하면 `price_basis='PCS'`(접두사 정규화)로 문서에 전달된다. |
| ERR-15 | P2 과거의 자연어 누락 메시지가 보완 뒤에도 남는다 | **재현됨**(영향이 원본과 다름) | 실행: `missing_fields=["Buyer full legal name and address"]`가 남은 초안에서 값을 모두 채워 재검증해도 'Confirm missing information: Buyer full legal name and address'가 blocking에 남는다(원본 `validate_and_calculate`와 같은 규칙). 차이: 원본 화면은 이 경고를 느슨하게 봤지만(ERR-05) 이식본은 blocking이 곧 발송 차단이므로, **추출 자기 보고가 실제 값과 어긋나면 값 보충만으로 발송을 풀 수 없다**. `revise_trade_document`의 `apply_review_value`는 값을 문자열로만 넣어 목록 키(`missing_fields`)를 지우는 데 쓸 수 없다 — 잠재 운영 이슈로 남긴다(아래 '뒤에 남는 이슈'). |

## 요약

- 재현됨(원본 재현 유지·계획대로): ERR-01(단가 잔존), ERR-02, ERR-03, ERR-04, ERR-07, ERR-08, ERR-09, ERR-10, ERR-12, ERR-15 — 이 중 ERR-04·ERR-08은 계약 15.8절이 사본·이식본 동일성을 위해 **의도적으로** 원본 재현 상태로 둔 것이고, 매칭 계열(ERR-02·03·09·10·11·12)은 전부 사본과 이식본이 같은 결과를 냈다.
- 재현 안 됨: ERR-05(화면 미이식 + 발송 조건이 blocking과 일치), ERR-06(원본 후속 수정 반영), ERR-13(이식 규칙대로 고침, 전용 테스트 있음), ERR-14(사본 후속 버전에서 이미 고쳐짐).
- ERR-01·ERR-15는 동작은 재현되지만 이식본에서 **발송 차단으로 이어져** 원본보다 안전한 쪽으로 작동한다(원본의 "버튼 활성" 문제는 없다).

## 뒤에 남는 이슈(후속 작업 후보)

1. **ERR-15 잔존 메시지가 발송을 영구히 막을 수 있다**: 추출 자기 보고(`missing_fields`) 문구가 코드 필수 항목 검사(계약 15.3절)와 어긋나면, 값을 다 채워도 'Confirm missing information: …'이 blocking에서 지워지지 않는다. 검토 입력에서 자연어 자기 보고 목록을 비우는 방법(예: `revise_trade_document` 확장)이 필요하다.
2. **ERR-04·ERR-08은 재현 상태로 남아 있다**(계약 15.8절 방침). 근거 검증에 `product_code`를 포함하고, 번역 근거 우회 범위를 좁히는 것이 후보다.
3. **ERR-02·03(소수점 충돌)·ERR-07(기준 통화 불일치)**: 사본·이식본 동일성이 우선이라 그대로 두었다. 매칭 개선은 원본과 함께 결정할 사항이다.
