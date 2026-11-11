# trade-domain-api 1~4절 완료 검증

기준: `codex/trade-domain-api`, 2026-11-11. 운영 DB·실제 Gemini/Gmail·Render·React 화면은 시험하지 않았다. 모든 사용자/회사/가격/이미지는 가상이다.

| 요구 | 확인 근거 |
|---|---|
| 기존 DB 데이터 보존 갱신 | `tests/test_trade_upgrade.py`, 실제 PostgreSQL의 `test_existing_postgres_data_and_constraints_are_upgraded` |
| 기존 문서 버전 초기 보관 | `test_review_migration_backfills_existing_document_version_without_losing_data`: 이전 리비전과 문서 7번 버전을 두고 실제 갱신 2회 후 원본/버전 보존 |
| 통화·상품 변경 시 가격 재검증 | 기존 수정 서비스 회귀 + `test_pi_currency_revision_reprices_and_renders_the_selected_bank_currency`: USD→EUR 뒤 EUR 단가와 계좌로 PDF/XLSX 확인 |
| 수정/발송 충돌 방지 | `test_edit_between_pdf_snapshot_and_claim_cannot_send_stale_document`, `test_sending_document_is_not_editable_and_failed_send_releases_claim` |
| PI 독립 실행과 AI 권한 분리 | `tests/test_pi_domain.py`: DB/HTTP/그래프 없이 실행, 직접/추출 같은 계산, 가격 override/원문 근거 보호 |
| PO·CI·PL 독립 업무 | `tests/test_trade_domain_operations.py`: 주입한 메모리 저장소와 가짜 추출로 같은 결과, PO 매입가·CI 원본 가격·PL 원본 합계 확인 |
| 네 문서 실제 API 흐름 | `tests/test_pi_api.py`, `test_each_domain_cancel_modify_approve_download_and_version_history`: 작성·조회·수정·버전·검토·취소·수정 후 재검토·승인·PDF/XLSX 다운로드·다른 사용자 거부 |
| 승인 제안/파일 불변과 재실행 | PI API 시험의 해시 변조·오래된 버전·렌더 실패/재시도·설정 변경 후 이미지/계좌 보존·DB 재연결 뒤 같은 파일 |
| 여러 연결의 동시 승인 | 실제 PostgreSQL 두 Database 연결·Barrier 렌더 동기화 후 동시에 승인, 같은 파일 ID·두 형식만 저장 |
| CI 가격·0원·증정 보존 | 승인 PI 이후 카탈로그 가격과 PI 현재 버전을 바꿔도 선택한 이전 버전의 금액 유지. 0원 샘플 및 PDF FOC 한 번 표시 |
| PL 합계 명시적 확인 | 원본/계산 합계 차이 확인, 계산값 적용·원본 보존·PCS/KG 분리·5×40FT를 개수 5로 유지·취소 복원·수정 후 재확인·잘못된 중량 행 승인 거부 |
| LangChain 진입점 구분 | 각 HTTP extract에서 별도 PI/PO/CI/PL Extraction 형식이 호출됨을 가짜 모델로 확인. AI의 일반 상품 샘플 위장은 원문 근거 검사로 차단 |
| 기존 동작 유지 | 전체 기존 Gmail/국내 견적/가격·프로모션·원본 parity/PDF 페이지 분할/직인 보호 시험 함께 통과 |

최종 로컬 결과:

- `uv run pytest`: **590 passed, 1 skipped**. 건너뛴 것은 별도 환경을 사용하는 PostgreSQL 시험 모듈이다.
- `uv run --with pgserver==0.1.4 pytest tests/test_trade_postgres.py -q`: **3 passed**. 임시 실제 PostgreSQL에서 이전 DB 갱신, PI API+서로 다른 연결의 동시 승인, PO/CI/PL API 전체 흐름을 확인했다. pgserver는 프로젝트 의존성으로 추가하지 않았다.
- `python3 .work/check.py`: 통과(경고 0개). 파일 지도·문서 포함 규칙을 확인했다.
- `git diff --check`: 공백 오류 없음.

이 기록은 `reference/kekorea/KNOWN_ERRORS.md`의 모든 오류를 해결했다는 뜻이 아니다. 기존 알려진 오류 점검표는 `20261110_kekorea_port_err_check.md`이며 이번 범위는 계획 1~4절이다. 원본의 첨부 OCR·운영 배포·새 마스터 챗봇은 추가하지 않았다.
