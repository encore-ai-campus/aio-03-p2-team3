import { useSearchParams } from "react-router-dom"
import { useAuth } from "../useAuth"
import KnowledgePage from "../knowledge/KnowledgePage"
import IssuedDocuments from "./IssuedDocuments"
import "./documents.css"

// 문서함: 생성된 문서(무역 PI·PO·CI·PL)와 업로드된 문서(지식 문서)를 탭으로 나눠
// 메타데이터 목록만 보여 준다. 상세 흐름은 각 기존 화면에 그대로 둔다(documents-v2 계획).
export default function DocumentsPage() {
  const { state } = useAuth()
  const [params, setParams] = useSearchParams()
  const tab = params.get("tab") === "issued" ? "issued" : "uploaded"

  function selectTab(next) {
    if (next === tab) return
    // 업로드 탭은 선택한 문서(원본 대조 화면)를 유지하고, 생성 탭으로 옮길 때는 끊는다.
    const nextParams = next === "uploaded" && params.get("document")
      ? { tab: next, document: params.get("document") }
      : { tab: next }
    setParams(nextParams)
  }

  return <div className="doc-workspace">
    <div className="page-head">
      <div>
        <h1 className="page-title">문서함</h1>
        <p className="page-sub">생성한 무역 문서와 올린 참고 문서의 메타데이터를 한 곳에서 확인합니다.</p>
      </div>
    </div>
    <div className="doc-tabs" role="tablist" aria-label="문서 종류">
      <button type="button" role="tab" aria-selected={tab === "issued"} className="doc-tab" onClick={() => selectTab("issued")}>생성된 문서</button>
      <button type="button" role="tab" aria-selected={tab === "uploaded"} className="doc-tab" onClick={() => selectTab("uploaded")}>업로드된 문서</button>
    </div>
    <div key={tab} className="doc-panel" role="tabpanel">
      {tab === "issued" ? <IssuedDocuments token={state.accessToken} /> : <KnowledgePage />}
    </div>
  </div>
}
