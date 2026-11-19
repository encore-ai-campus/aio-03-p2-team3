import { useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { LABELS as TRADE_LABELS } from "../trade/fieldLabel"
import DocCard from "./DocCard"
import { CalendarChangeCard } from "./CalendarChangeCard"

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

const PI_OPTIONS = {
  currency: ["USD", "KRW", "EUR", "CNY"].map(code => [code, code]),
  product_family: [["other", "기타"], ["cosmetics", "화장품"], ["polysilicon", "폴리실리콘"],
    ["wafer", "웨이퍼"], ["solar_cell", "태양전지"], ["solar_module", "태양광 모듈"]],
}

const PI_ERRORS = {
  PI_NUMBER_DUPLICATE: "이미 사용 중인 PI 문서번호입니다. 다른 번호를 입력해 주세요.",
  PI_COMPLETION_INVALID: "입력 형식과 할인율 범위(0~100%)를 확인해 주세요.",
  document_changed: "다른 곳에서 이 PI가 수정되었습니다. 최신 항목을 확인한 뒤 다시 진행해 주세요.",
}

function PIField({ path, answers, change, busy }) {
  const key = path.split(".").at(-1)
  const label = key === "document_number" ? "PI 문서번호" : TRADE_LABELS[key]
  const value = answers[path] ?? ""
  const options = PI_OPTIONS[key]
  const override = path.replace(/unit_price$/, "confirm_price_override")
  const common = { value, disabled: busy, onChange: event => change(path, event.target.value) }
  const [discountMode, setDiscountMode] = useState(() => !value ? "" : value === "0" ? "none" : "custom")
  if (key === "discount_percent") {
    return <div className="pi-completion-discount">
      <label className="q-field"><span>할인율</span>
        <select value={discountMode} disabled={busy} onChange={event => {
          const mode = event.target.value
          setDiscountMode(mode)
          change(path, mode === "none" ? "0" : "")
        }}>
          <option value="">할인 조건 선택</option>
          <option value="none">할인 없음(0%)</option>
          <option value="custom">할인율 직접 입력</option>
        </select>
      </label>
      {discountMode === "custom" && <label className="q-field"><span>{label}</span>
        <input {...common} type="number" min="0" max="100" step="any" required />
      </label>}
    </div>
  }
  return <div>
    <label className="q-field"><span>{label}</span>
      {options ? <select {...common}>
        <option value="">선택해 주세요</option>
        {options.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
      </select> : key === "address" ? <textarea {...common} rows={2} maxLength={4000} />
        : <input {...common} inputMode={["quantity", "unit_price"].includes(key) ? "decimal" : undefined} maxLength={4000} />}
    </label>
    {key === "unit_price" && value.trim() && <label className="pi-completion-override">
      <input type="checkbox" checked={Boolean(answers[override])} disabled={busy}
        onChange={event => change(override, event.target.checked)} /> 입력한 단가 사용 확인
    </label>}
  </div>
}

function PICompletion({ completion, busy, onSave }) {
  const [answers, setAnswers] = useState(completion.attempted)
  const change = (path, value) => setAnswers(previous => ({ ...previous, [path]: value }))
  const [addingItem, setAddingItem] = useState(false)
  const { fields, item_names: names, bank_missing: banks } = completion
  const itemFields = fields.filter(path => path.startsWith("items."))
  const terms = fields.filter(path => !path.includes("."))
  const parties = [["buyer", "구매자"], ["seller", "판매자"]].map(([role, label]) =>
    [label, fields.filter(path => path.startsWith(role + "."))]).filter(([, paths]) => paths.length)
  const groups = [["거래 조건", terms], ["거래처", parties.flatMap(([, paths]) => paths)], ["품목", itemFields]]
    .filter(([, paths]) => paths.length)
  const changes = Object.fromEntries(fields.filter(path => typeof answers[path] === "string" && answers[path].trim())
    .map(path => [path, answers[path].trim()]))
  for (const path of Object.keys(changes).filter(path => path.endsWith(".unit_price"))) {
    const override = path.replace(/unit_price$/, "confirm_price_override")
    if (answers[override]) changes[override] = true
  }

  const hasChanges = Object.keys(changes).length > 0
  const renderFields = paths => <div className="q-fields">{paths.map(path =>
    <PIField key={path} path={path} answers={answers} change={change} busy={busy} />)}</div>
  return <form onSubmit={event => { event.preventDefault(); onSave(changes) }}>
    {completion.error && <p className="form-error" role="alert">{PI_ERRORS[completion.error]}</p>}
    {fields.length > 0 && <p className="review-note">보완할 항목 {fields.length}개</p>}
    <div className="pi-completion-groups">{groups.map(([label, paths], index) =>
      <details key={label} open={index === 0 || fields.length <= 3}>
        <summary>{label} · {label === "품목" && !names.length ? "등록된 품목 없음" : `${paths.length}개`}</summary>
        {label === "거래처" ? parties.map(([role, partyPaths]) =>
          <fieldset key={role}><legend>{role}</legend>{renderFields(partyPaths)}</fieldset>)
          : label === "품목" ? <>
            {!names.length && !addingItem ? <button className="btn" type="button" disabled={busy} onClick={() => setAddingItem(true)}>첫 품목 추가</button>
              : (names.length ? names : [null]).map((name, itemIndex) => {
                const rowPaths = paths.filter(path => path.startsWith(`items.${itemIndex}.`))
                return rowPaths.length > 0 && <fieldset key={itemIndex}>
                  <legend>품목 {itemIndex + 1}{name && ` · ${name}`}</legend>{renderFields(rowPaths)}
                </fieldset>
              })}
          </> : renderFields(paths)}
      </details>)}</div>
    {banks.length > 0 && <p className="review-note">지급 계좌 정보 {banks.length}개 누락 · <Link to="/settings?section=banks" target="_blank">계좌 설정 열기</Link></p>}
    {!fields.length && !banks.length && !completion.error && <p className="review-note">PI 문서에서 검토가 필요한 항목을 확인해 주세요.</p>}
    <footer className="review-actions pi-completion-actions">
      <Link className="btn" to={`/trade/pi/${completion.document_id}`} target="_blank">PI 문서 열기</Link>
      {!hasChanges && <button className="btn" type="button" disabled={busy} onClick={() => onSave({})}>다시 확인</button>}
      <button className="btn blue" disabled={busy || !hasChanges}>저장하고 계속</button>
    </footer>
  </form>
}

export default function ReviewCard({ waiting, results, piCompletion, busy, onResume }) {
  const region = useRef(null)
  const [answers, setAnswers] = useState({})
  const [error, setError] = useState("")
  useEffect(() => { region.current?.focus() }, [])
  const approval = waiting.kind === "approval"
  const action = waiting.action
  const payload = action?.payload
  const editingReply = approval && action.operation === "edit_reply"
  const mail = approval && action.domain === "mail" && !editingReply
  const calendar = approval && action.domain === "calendar"
  const calendarTitle = { create: "이 일정을 등록할까요?", move_event: "이 일정의 시각을 변경할까요?", cancel_event: "이 일정을 취소할까요?" }
  const calendarApprove = { create: "확인하고 등록", move_event: "확인하고 변경", cancel_event: "확인하고 일정 취소" }
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
        <h2 className="review-title">{editingReply ? "이 답장 초안을 수정할까요?" : mail ? "이 메일을 보내도 될까요?" : calendar ? calendarTitle[action.operation] : packing ? "포장 합계를 승인할까요?" : "이 문서를 발급할까요?"}</h2>
      </header>
      {editingReply ? <div className="mail-frame reply-edit-review">
        <div className="mail-subject">{payload.original.label} · {payload.changes.subject}</div>
        <div className="mail-body"><b>수정 전</b><p>{payload.original.body}</p></div>
        <div className="mail-body"><b>수정 후</b><p>{payload.changes.body}</p></div>
      </div> : mail ? <>
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
      </> : calendar ? <CalendarChangeCard action={action} /> : <>
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
        <button className="btn" disabled={busy} onClick={() => decide("cancel")}>{calendar ? "그만두기" : "취소"}</button>
        <button className="btn blue" disabled={busy} onClick={() => decide("approve")}>{editingReply ? "수정 내용 저장" : mail ? <>{SEND_ICON}확인하고 보내기</> : calendar ? calendarApprove[action.operation] : "확인하고 승인"}</button>
      </footer>
    </> : piCompletion ? <>
      <header className="review-head">
        <Badge tone="amber">답변 대기</Badge>
        <h2 className="review-title">{waiting.message}</h2>
      </header>
      <PICompletion completion={piCompletion} busy={busy}
        onSave={changes => onResume({ task_id: waiting.task_id, answers: { pi_changes: changes } })} />
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
