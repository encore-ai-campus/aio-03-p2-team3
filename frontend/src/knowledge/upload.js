// 지식 문서 업로드 절차 — 문서함 셸(documents/DocumentsPage)이 올리기 버튼을 갖고
// 도메인 경로·오류 안내·파일별 업로드는 여기 한 곳에 둔다. KnowledgePage 상세도 같은 안내를 쓴다.
import { apiFetch } from "../api.js"

export const KNOWLEDGE_ROOT = "/knowledge/documents"

export const KNOWLEDGE_ERRORS = { LOCAL_KEY_REQUIRED: "로컬 .env에 OPENAI_API_KEY를 지정하고 앱을 다시 시작해 주세요.", LOCAL_RUNTIME_REQUIRED: "전용 로컬 실행 명령(uv run python -m app.local)으로 앱을 다시 시작해 주세요.", provider_rate_limit: "AI 사용 한도를 확인한 뒤 다시 시도해 주세요.", provider_access_denied: "설정에 등록한 키와 모델 이용 권한을 확인해 주세요.", LOCAL_WORKER_KEY_FORBIDDEN: "현재 개인 PC 실행 방식은 문서함의 이미지·임베딩 요청을 지원하지 않습니다.", OPENAI_KEY_REQUIRED: "설정에서 본인의 OpenAI 키를 등록해 주세요.", office_not_installed: "서버에 LibreOffice가 필요합니다. PDF로 변환해 올릴 수도 있습니다.", processing_interrupted: "처리가 중단되었습니다. 이전 저장 결과는 보존됩니다. 확인 후 다시 시도해 주세요.", hidden_sheet: "숨김 시트를 표시하거나 필요한 내용을 PDF로 내보내 주세요.", formula_cache_missing: "Excel에서 수식을 재계산·저장하거나 PDF로 내보내 주세요." }

// 파일별 업로드 결과 [{name, id?, message}]를 돌려준다. 한 파일의 실패가 나머지를 막지 않는다.
export async function uploadKnowledgeFiles(files, token) {
  const results = []
  for (const file of files) {
    try {
      if (file.size > 20 * 1024 * 1024) throw new Error("20MiB를 넘습니다. 파일을 나누어 주세요.")
      const form = new FormData()
      form.append("file", file)
      const data = await apiFetch(KNOWLEDGE_ROOT, { method: "POST", token, body: form })
      results.push({ name: file.name, id: data.id,
        message: data.duplicate ? "같은 원본이 등록되어 있습니다. 기존 처리 결과를 표시합니다." : "업로드 완료 · 처리 대기" })
    } catch (error) {
      results.push({ name: file.name, message: KNOWLEDGE_ERRORS[error.code] ?? error.message })
    }
  }
  return results
}
