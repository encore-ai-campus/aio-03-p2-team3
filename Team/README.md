# 팀 공유 — KE KOREA 개인 에이전트에서 검증한 기능 제안

> **참고 제안 문서 · 2026-11-11. 팀 프로젝트 구현 완료 목록이 아닙니다.**
> 현재 팀 프로젝트는 **Gmail 기반 거래 응답·견적서 처리와 독립 PI/PO/CI/PL 무역 문서 API**를 가진 FastAPI/Gemini 기반 에이전트입니다. KE KOREA 개인 저장소는 **Streamlit/OpenAI/Supabase** 기반 계약/무역 문서 에이전트이므로 코드를 무작정 복사하지 마세요. 팀 프로젝트의 실제 구조·계획·결정은 [프로젝트 맥락](../docs/PROJECT_CONTEXT.md), [작업 계약](../docs/CONTRACT.md), [팀 규칙](../AGENTS.md)이 우선입니다.

## 개인 프로젝트에서 2026-11-11 적용한 개선 사례 (재구현 후보)

| 후보 ID | 기능과 기대 동작 | 개인 저장소 근거 | 팀 프로젝트 적용 판정 |
| --- | --- | --- | --- |
| K01 | AI 근거 인용 검증: 유효한 원문 근거만 유지, 허위 인용은 제거·사용자 확인 대상으로 표시, 원 데이터는 미승인 유지 | [PR #24](https://github.com/swihm1989-ship-it/KE_KOREA_CO_LTD/pull/24) | **추천:** Gmail 거래정보 추출 `source`와 연결 가능. 팀 스키마 확인 필요 |
| K02 | AI가 만든 본문 품질 검사 중 인용이 불일치해도 재검증 1회 후 검토용 작업물 보존, 확정/발송은 차단 | [PR #25](https://github.com/swihm1989-ship-it/KE_KOREA_CO_LTD/pull/25) | **추천:** 견적서·답장 후보의 실패 복구 패턴으로 응용. 기존 오류 계약 우선 |
| K03 | AI 작업 Checkpointer와 사람 승인 Interrupt, `thread_id` 분리. DB 승인기록과 임시 실행상태를 구분 | [PR #21](https://github.com/swihm1989-ship-it/KE_KOREA_CO_LTD/pull/21) | **조건부:** 팀 기존 `AgentState`·승인/발송 분리 설계 확인 후 논의 |
| K04 | 거래조건을 2열 표로 표시하고 내부 승인 상태는 본문 출력에서 분리. 미승인 상태·최종 출력 제한은 유지 | [PR #20](https://github.com/swihm1989-ship-it/KE_KOREA_CO_LTD/pull/20), [#27](https://github.com/swihm1989-ship-it/KE_KOREA_CO_LTD/pull/27) | **추천:** 견적서 PDF/UI 명세 표·내부 경고 분리. 실제 템플릿은 팀 설계 우선 |
| K05 | 기존 저장 문서의 `제안(미확정)` 접두어를 화면에서만 숨기고 승인값은 변경하지 않음 | [PR #22](https://github.com/swihm1989-ship-it/KE_KOREA_CO_LTD/pull/22) | 조건부: 상태 문구 중복이 발생할 때만 |
| K06 | 문장 클릭 시 메모·수정안/삭제 확인 후에만 새 revision 저장; 취소·충돌·다른 문장 보존 | [PR #23](https://github.com/swihm1989-ship-it/KE_KOREA_CO_LTD/pull/23) | **선택:** 팀 MVP에서 문장 단위 편집이 필요한지 먼저 합의 |
| K07 | 긴 문장 클릭 위치가 줄 아래로 밀리는 문제: 투명 absolute overlay 대신 실제 보이는 버튼을 전체 클릭 영역으로 사용 | [PR #26](https://github.com/swihm1989-ship-it/KE_KOREA_CO_LTD/pull/26) | 팀 화면에 같은 버그가 있을 때만. Streamlit CSS를 HTMX로 그대로 복사하지 않음 |
| K08 | 저장된 문서의 이름과 출력 문서의 제목을 일치시키는 revision 기반 제목 변경 | **이미 있던 개인 기능** `ui.py`·`exports.py` | 선택 기능. 개인 저장 목록의 별도 Rename PR [#28](https://github.com/swihm1989-ship-it/KE_KOREA_CO_LTD/pull/28)은 병합 없이 종료. 이미 팀에 있으면 수정 금지 |

### 주의: 구현 사실과 효과의 구분
- 개인 레포 PR #20~#27은 병합됐지만 팀 레포에는 **아직 도입되지 않았다**. 실제 배포 Streamlit 종단 간 검증 완료를 뜻하지 않는다.
- Checkpointer는 개인 레포에서 **실행 단위 메모리 기반**이므로 서버 재시작 후 복구 기능이 아니다. Interrupt는 기존 승인 절차를 보조할 뿐 자동 승인하지 않는다.
- 한 차례 화면에서 초안 생성 **52.2초**, 품질 감사 **66.9초**, RAG 검색 **0.7초**가 기록되었다. 합계 약 **119.8초**이며 평균 속도나 최적화 성공을 의미하지 않는다.
- 실제 개인·거래처 정보, 은행정보, 비밀값, 원본 계약서를 팀 레포·AI 프롬프트·테스트에 넣지 않는다. 가상 데이터만 사용한다.

## 팀원 선택 구현: “해줘” 프롬프트

아래 템플릿에서 **후보 ID 한 개만** 선택한 후 AI에게 요청한다. 그냥 "해줘"만 보낼 때에도 바로 앞의 후보를 지정해야 다른 기능이 함께 바뀌지 않는다.

```text
우리 팀 레포 encore-ai-campus/aio-03-p2-team3에서 Team/README.md의 [K01 등 후보 ID] 기능을 구현해줘.
먼저 현재 코드와 docs/PROJECT_CONTEXT.md, docs/CONTRACT.md, .work/TASK.md를 읽고
동등 기능이 이미 있으면 아무것도 수정하지 않고 구현 위치와 테스트 근거를 보고해줘.
없다면 현재 FastAPI/Gemini/HTMX/DB 및 app/trade 구조에 맞게 해당 기능 하나만 설계해줘.
KE_KOREA_CO_LTD는 읽기 전용 참고로 사용하고 절대로 수정하지 마.
기존 AgentState/도구 스키마/사용자 승인·발송 제한/테스트/비밀정보 보호는 유지해.
필요하면 먼저 팀원에게 설계 변경을 확인받고, 별도 브랜치와 PR에서 변경하며
정상/오류/중복/취소 테스트 및 .work/check.py, uv run pytest 결과를 알려줘.
기능이 둘 이상이면 먼저 docs/plans에 작업 분할 계획만 작성해줘.
Issue: (있으면 번호를 넣기)
```

**검증 공통 기준:** (1) 기존 입력→출력 결과 유지, (2) 사용자의 명시적 승인 없는 발송·계약 확정 금지, (3) 후보·근거·실패 상태를 구분, (4) 값/환율/수량·문서 본문 임의 변경 금지, (5) 기존 테스트와 새 기능 테스트 통과, (6) 실제 서비스 검증 전 '배포 완료'라고 말하지 않음.

## 개인 저장소 원문 참조
- [개인 Team README](https://github.com/swihm1989-ship-it/KE_KOREA_CO_LTD/blob/main/Quotation_KEKOREA/Team/README.md)
- [개인 Presentation README](https://github.com/swihm1989-ship-it/KE_KOREA_CO_LTD/blob/main/Quotation_KEKOREA/Presentation/README.md)
- 팀 발표 관점 요약: [Presentation/README.md](../Presentation/README.md)


## 이 저장소의 실제 무역문서 코드와 비교

본 저장소에는 이미 `app/trade/{pi,po,ci,pl,common,review,settings}` 구조와 승인·검토 API가 존재한다. [trade-api](../docs/trade-api.md)와 [trade-domain-api 계획](../docs/plans/trade-domain-api.md)을 먼저 확인한다. K04 거래표/출력, K06 검토 승인, K08 제목 변경 등은 **기존 구현과 비교해 빠진 요구사항이 있을 때만** 추가한다. 팀 README는 코드를 덮어쓰라는 지시가 아니며, 계약서 기능을 무역문서에 그대로 이식하라는 뜻도 아니다.
