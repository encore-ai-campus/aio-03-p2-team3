import { useEffect, useRef, useState } from "react"
import DocCard from "./DocCard"

/* 시안 docs/plans/agent-chat-ui — 확인 카드: 배지 + 메일 프레임 + 문서 카드(승인), 항목별 입력(질문). */

const LABELS = { response: "답변", candidate_id: "답장 후보", kind: "문서 종류", document_id: "문서 ID",
  values: "보완할 문서 입력값 (JSON)", text: "문서 원문", thread_id: "메일 스레드 ID" }
const HINTS = { values: "JSON 객체 한 덩어리로 입력합니다. 예: { \"buyer_address\": \"서울특별시 …\" }" }
const KIND_OPTIONS = ["PI", "PO", "CI", "PL"]

const CLOCK_ICON = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
const REPLY_ICON = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 17l-5-5 5-5" /><path d="M4 12h11a4 4 0 0 1 4 4v2" /></svg>
const CLIP_ICON = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21.4 11.05L12.2 20.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 1 1 5.7 5.7l-9.2 9.1a2 2 0 0 1-2.8-2.8l8.5-8.5" /></svg>
const SEND_ICON = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M22 2L11 13" /><path d="M22 2l-7 20-4-9-9-4z" /></svg>

function Badge({ tone, children }) {
  return <span className={`badge ${tone}`}>{CLOCK_ICON}{children}</span>
}

function AttachChips({ files }) {
  return <div className="attach-row">{files.map(file => {
    const ext = (file.file_format || file.filename.split(".").pop() || "").toUpperCase()
    return <span className="attach-chip" key={file.id}>{CLIP_ICON}{file.filename}{ext && <em>{ext}</em>}</span>
  })}</div>
}

function tradePartyNames(document) {
  const from = document?.seller?.legal_name || document?.seller?.company_name
  const to = document?.buyer?.company_name || document?.buyer?.legal_name
  return from && to ? { from, to } : null
}

function tradeTotal(document) {
  return document?.total != null && document.total !== "" ? `${document.currency || ""} ${document.total}`.trim() : null
}

function MailDocumentCard({ payload }) {
  const document = payload.document
  if (payload.trade_doc_id) {
    const kind = (payload.files?.[0]?.kind || "").toLowerCase()
    return <DocCard chip={kind ? kind.toUpperCase() : "문서"} chipClass={kind} number={document.document_number || "승인·발급 시 문서번호 자동 생성"}
      parties={tradePartyNames(document)} total={tradeTotal(document)} meta={`승인 버전 ${payload.revision} · 이번 발송에 고정`}
      link={kind ? `/trade/${kind}/${payload.trade_doc_id}` : null} />
  }
  return <DocCard chip="견적" chipClass="quote" number={document.quote_no}
    parties={document.supplier && document.customer_name ? { from: document.supplier.company_name || document.supplier.name, to: document.customer_name } : null}
    total={document.total != null ? `KRW ${document.total}` : null}
    meta={[document.quote_date, `상태 ${document.status === "ready" ? "발송 가능" : document.status}`].filter(Boolean).join(" · ")} />
}

function QuestionField({ field, label, value, onChange, candidates, busy }) {
  const hint = HINTS[field]
  const common = { "aria-label": label, value, onChange: event => onChange(event.target.value), disabled: busy }
  return <label className="q-field" key={field}><span>{label}</span>{hint && <small>{hint}</small>}
    {field === "candidate_id" && candidates.length ? <select {...common} required>
        <option value="">직접 선택해 주세요</option>
        {candidates.map(candidate => <option key={candidate.id} value={candidate.id}>#{candidate.id} {candidate.label} — {candidate.subject}</option>)}
      </select>
    : field === "kind" ? <select {...common} required>
        <option value="">직접 선택해 주세요</option>
        {KIND_OPTIONS.map(kind => <option key={kind} value={kind}>{kind}</option>)}
      </select>
    : field.endsWith("_id") ? <input type="text" inputMode="numeric" {...common} required />
    : <textarea className={field === "values" ? "code" : undefined} rows={field === "values" ? 6 : 3} {...common} required />}
  </label>
}

export default function ReviewCard({ waiting, results, busy, onResume }) {
  const region = useRef(null)
  const [answers, setAnswers] = useState({})
  const [error, setError] = useState("")
  useEffect(() => { region.current?.focus() }, [])
  const approval = waiting.kind === "approval"
  const action = waiting.action
  const payload = action?.payload
  const mail = approval && action.domain === "mail"
  const packing = action?.operation === "approve_packing"
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
  return <section className={`card agent-review ${approval ? "approve" : "question"}`} role="region"
    aria-label={approval ? "작업 최종 확인" : "추가 정보 입력"} tabIndex={-1} ref={region}>
    {approval ? <>
      <header className="review-head">
        <Badge tone="blue">승인 대기</Badge>
        <h2 className="review-title">{mail ? "이 메일을 보내도 될까요?" : packing ? "포장 합계를 승인할까요?" : "이 문서를 발급할까요?"}</h2>
      </header>
      {mail ? <>
        <div className="mail-frame">
          <div className="mail-head">
            <span className="mail-dir">{REPLY_ICON}</span>
            <div className="mail-to"><small>받는 사람</small><b>{payload.headers?.["reply-to"] || payload.headers?.from}</b></div>
            {payload.candidate_id && <span className="mail-kind">답장 후보 #{payload.candidate_id}</span>}
          </div>
          {payload.subject && <div className="mail-subject">{payload.subject}</div>}
          <div className="mail-body">{payload.body}</div>
        </div>
        {payload.files?.length > 0 && <AttachChips files={payload.files} />}
        {payload.document && <MailDocumentCard payload={payload} />}
        <p className="review-note">같은 메일 대화로 발송됩니다. 문서 발급과 메일 발송은 별개입니다.</p>
      </> : <>
        {payload.preview?.document ? <DocCard hero chip={payload.kind} chipClass={payload.kind?.toLowerCase()}
          number={payload.preview.document.document_number || "승인·발급 시 문서번호 자동 생성"}
          parties={tradePartyNames(payload.preview.document)}
          itemsNote={payload.preview.document.items?.length ? `품목 ${payload.preview.document.items.length}건 · 버전 ${payload.revision}` : `버전 ${payload.revision}`}
          items={payload.preview.document.items} total={tradeTotal(payload.preview.document)}
          link={`/trade/${payload.kind.toLowerCase()}/${payload.document_id}`} />
        : <p>문서 #{payload.document_id} · 버전 {payload.revision} · {packing ? "포장 합계 승인" : "파일 발급"}</p>}
        <p className="review-note">{packing ? "원본과 계산 합계가 같은지 확인한 뒤 승인해 주세요." : "문서 발급은 메일 발송과 별개입니다. 승인 버전의 내용이 고정됩니다."}</p>
      </>}
      <footer className="review-actions">
        <button className="btn" disabled={busy} onClick={() => decide("cancel")}>취소</button>
        <button className="btn blue" disabled={busy} onClick={() => decide("approve")}>{mail ? <>{SEND_ICON}확인하고 보내기</> : "확인하고 승인"}</button>
      </footer>
    </> : <form onSubmit={answer}>
      <header className="review-head">
        <Badge tone="amber">답변 대기</Badge>
        <h2 className="review-title">{waiting.message}</h2>
      </header>
      <div className="q-fields">
        {waiting.fields.map(field => <QuestionField key={field} field={field} label={LABELS[field] || field}
          value={answers[field] || ""} onChange={value => setAnswers({ ...answers, [field]: value })}
          candidates={candidates} busy={busy} />)}
      </div>
      {error && <p role="alert" className="form-error">{error}</p>}
      <footer className="review-actions"><button className="btn blue" disabled={busy}>답변하고 계속</button></footer>
    </form>}
  </section>
}
