import { useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { useAuth } from "../useAuth"
import KnowledgePage from "../knowledge/KnowledgePage"
import { uploadKnowledgeFiles } from "../knowledge/upload.js"
import IssuedDocuments from "./IssuedDocuments"
import "./documents.css"

// 문서함: 생성된 문서(무역 PI·PO·CI·PL)와 업로드된 문서(지식 문서)를 탭으로 나눠
// 메타데이터 목록만 보여 준다. 업로드는 탭 줄 오른쪽 버튼 하나로 한다(documents-v2 계획 + 요청자 검토).
export default function DocumentsPage() {
  const { state } = useAuth()
  const [params, setParams] = useSearchParams()
  const tab = params.get("tab") === "issued" ? "issued" : "uploaded"
  const files = useRef(null)
  const [uploads, setUploads] = useState([])
  const [uploading, setUploading] = useState(false)
  const [uploadTick, setUploadTick] = useState(0)

  function selectTab(next) {
    if (next === tab) return
    // 업로드 탭은 선택한 문서(원문 대조 화면)를 유지하고, 생성 탭으로 옮길 때는 끊는다.
    setParams(next === "uploaded" && params.get("document")
      ? { tab: next, document: params.get("document") }
      : { tab: next })
  }

  async function pickFiles(event) {
    const selected = Array.from(event.target.files ?? [])
    event.target.value = "" // 같은 파일을 다시 선택해도 올라가게 한다.
    if (!selected.length || uploading) return
    setUploading(true)
    setUploads(selected.map((file) => ({ name: file.name, message: "업로드 대기" })))
    const results = await uploadKnowledgeFiles(selected, state.accessToken)
    setUploads(results)
    setUploading(false)
    setUploadTick((value) => value + 1) // 업로드된 문서 목록을 다시 읽는다.
  }

  return <div className="doc-workspace">
    <div className="page-head">
      <div>
        <h1 className="page-title">문서함</h1>
        <p className="page-sub">생성한 무역 문서와 올린 참고 문서의 메타데이터를 한 곳에서 확인합니다.</p>
      </div>
    </div>
    <div className="doc-tabbar">
      <div className="doc-tabs" role="tablist" aria-label="문서 종류">
        <button type="button" role="tab" aria-selected={tab === "issued"} className="doc-tab" onClick={() => selectTab("issued")}>생성된 문서</button>
        <button type="button" role="tab" aria-selected={tab === "uploaded"} className="doc-tab" onClick={() => selectTab("uploaded")}>업로드된 문서</button>
      </div>
      {tab === "uploaded" && <>
        <input ref={files} type="file" multiple hidden accept=".pdf,.docx,.xlsx,.txt,.png,.jpg,.jpeg" tabIndex={-1}
          aria-hidden="true" onChange={pickFiles} />
        <button type="button" className="doc-upload-btn" disabled={uploading} onClick={() => files.current?.click()}>
          {uploading ? "업로드 중…" : "문서 업로드"}</button>
      </>}
    </div>
    {!!uploads.length && tab === "uploaded" && (
      <ul className="doc-upload-note" aria-live="polite">
        {uploads.map((value, index) => <li key={index}>{value.name} — {value.message}</li>)}
      </ul>
    )}
    <div key={tab} className="doc-panel" role="tabpanel">
      {tab === "issued" ? <IssuedDocuments token={state.accessToken} /> : <KnowledgePage reloadKey={uploadTick} />}
    </div>
  </div>
}
