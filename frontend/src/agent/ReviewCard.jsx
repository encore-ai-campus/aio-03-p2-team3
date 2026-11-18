import { useEffect, useRef, useState } from "react"
import DocumentSnapshot from "../trade/DocumentSnapshot"

const LABELS = { response: "답변", candidate_id: "답장 후보", kind: "문서 종류", document_id: "문서 ID",
  values: "보완할 문서 입력값 (JSON)", text: "문서 원문", thread_id: "메일 스레드 ID" }

export default function ReviewCard({ waiting, results, busy, onResume }) {
  const region = useRef(null)
  const [answers, setAnswers] = useState({})
  const [error, setError] = useState("")
  useEffect(() => { region.current?.focus() }, [])
  const approval = waiting.kind === "approval"
  const action = waiting.action
  const payload = action?.payload
  const candidates = [...new Map(results.flatMap(item => item.data?.candidates || [])
    .filter(item => item && ["pending", "send_failed"].includes(item.status)).map(item => [item.id, item])).values()]

  function decide(decision) {
    onResume({ action_id: action.id, content_hash: waiting.content_hash, decision })
  }
  function answer(event) {
    event.preventDefault(); setError("")
    try {
      const parsed = Object.fromEntries(Object.entries(answers).filter(([, value]) => value.trim()).map(([key, value]) =>
        [key, key === "values" ? JSON.parse(value) : key.endsWith("_id") ? Number(value) : value]))
      if (!Object.keys(parsed).length) throw new Error("답변을 입력해 주세요.")
      onResume({ task_id: waiting.task_id, answers: parsed })
    } catch { setError("입력 형식을 확인해 주세요. 문서 입력값은 올바른 JSON 객체로 입력합니다.") }
  }
  return <section className="card agent-review" role="region" aria-label={approval ? "작업 최종 확인" : "추가 정보 입력"} tabIndex={-1} ref={region}>
    <h2 className="section-title">{approval ? "실행 전 확인해 주세요" : "추가 정보가 필요합니다"}</h2>
    {approval ? <>
      {action.domain === "mail" ? <>
        <p><b>받는 사람:</b> {payload.headers?.["reply-to"] || payload.headers?.from}</p>
        <p><b>제목:</b> {payload.subject}</p><p className="agent-text">{payload.body}</p>
        <p>답장 후보 #{payload.candidate_id} · 같은 메일 대화로 발송합니다.</p>
        {payload.files?.map(file => <p key={file.id}>첨부: {file.filename}</p>)}
        {(payload.quote_id || payload.trade_doc_id) && <p>연결 문서를 함께 발송합니다. 아래 고정된 내용을 확인해 주세요.</p>}
        {payload.document && <details><summary>첨부 문서 내용</summary><pre>{JSON.stringify(payload.document, null, 2)}</pre></details>}
      </> : <>
        <p>{payload.kind} #{payload.document_id} · 버전 {payload.revision} · {action.operation === "approve_packing" ? "포장 합계 승인" : "파일 발급"}</p>
        {payload.preview?.document && <DocumentSnapshot document={payload.preview.document} kind={payload.kind.toLowerCase()} />}
        <p>문서 발급은 메일 발송과 별개입니다.</p>
      </>}
      <div className="form-actions"><button className="btn" disabled={busy} onClick={() => decide("cancel")}>취소</button>
        <button className="btn blue" disabled={busy} onClick={() => decide("approve")}>{action.domain === "mail" ? "확인하고 보내기" : "확인하고 승인"}</button></div>
    </> : <form onSubmit={answer}>
      <p>{waiting.message}</p>
      {waiting.fields.map(field => <label className="agent-field" key={field}>{LABELS[field] || field}
        {field === "candidate_id" && candidates.length ? <select aria-label={LABELS[field] || field} value={answers[field] || ""} onChange={event => setAnswers({ ...answers, [field]: event.target.value })} required disabled={busy}>
          <option value="">직접 선택해 주세요</option>{candidates.map(candidate => <option key={candidate.id} value={candidate.id}>#{candidate.id} {candidate.label} — {candidate.subject}</option>)}
        </select> : <textarea aria-label={LABELS[field] || field} value={answers[field] || ""} onChange={event => setAnswers({ ...answers, [field]: event.target.value })} rows={field === "values" ? 7 : 3} disabled={busy} />}
      </label>)}
      {error && <p role="alert" className="form-error">{error}</p>}
      <button className="btn blue" disabled={busy}>답변하고 계속</button>
    </form>}
  </section>
}
