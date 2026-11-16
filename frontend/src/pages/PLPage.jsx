import { useEffect, useEffectEvent, useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { apiFetch, downloadFile } from "../api"
import { useAuth } from "../useAuth"
import AIInput from "../trade/AIInput"
import DocumentSnapshot from "../trade/DocumentSnapshot"
import PLForm from "../trade/PLForm"
import PackingReview from "../trade/PackingReview"
import { emptyPL, PL_STEPS, plDraft, plMissing, plNextScreen, plPayload, plSectionFor } from "../trade/pl-input"
import ReviewPanel from "../trade/ReviewPanel"

const STATUS = { needs_input: "입력 필요", ready: "검토 가능", issued: "발급 완료" }

export default function PLPage() {
  const { state } = useAuth()
  const token = state.accessToken
  const { documentId } = useParams()
  const navigate = useNavigate()
  const [resource, setResource] = useState(null)
  const [draft, setDraft] = useState(emptyPL)
  const [proposal, setProposal] = useState(null)
  const [formats, setFormats] = useState(["pdf", "xlsx"])
  const [dirty, setDirty] = useState(false)
  const [modifying, setModifying] = useState(false)
  const [loading, setLoading] = useState(Boolean(documentId))
  const [reload, setReload] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState("")
  const [screen, setScreen] = useState({ key: "start", fields: null })
  const [guided, setGuided] = useState(false)
  const [packing, setPacking] = useState(null)
  const [packingError, setPackingError] = useState("")
  const [packingLoading, setPackingLoading] = useState(false)
  const [packingReload, setPackingReload] = useState(0)
  const [settings, setSettings] = useState(null)
  const [settingsError, setSettingsError] = useState("")
  const question = useRef(null)
  const mutation = useRef(null)
  const base = "/trade/pl"

  function accept(document, review = null, next = { key: "review", fields: null }) {
    setResource(document)
    setDraft(plDraft(document.input))
    setProposal(review)
    if (review) setFormats(review.payload.formats)
    setDirty(false)
    setModifying(false)
    setScreen(next)
  }

  // 같은 사용자의 토큰 갱신으로 저장 전 입력을 다시 읽어 덮어쓰지 않는다.
  const read = useEffectEvent(async (id, signal) => {
    const document = await apiFetch(`${base}/${id}`, { token, signal })
    const review = document.proposal_id
      ? await apiFetch(`${base}/${id}/reviews/${document.proposal_id}`, { token, signal }) : null
    if (!signal.aborted) {
      setGuided(true)
      accept(document, review, document.status === "needs_input" ? plNextScreen(plDraft(document.input)) : undefined)
    }
  })
  useEffect(() => {
    const controller = new AbortController()
    mutation.current?.abort()
    mutation.current = null
    setBusy(false)
    setError(null)
    setNotice("")
    setResource(null)
    setProposal(null)
    setModifying(false)
    setDirty(false)
    if (!documentId) {
      setDraft(emptyPL())
      setScreen({ key: "start", fields: null })
      setGuided(false)
      setLoading(false)
    } else {
      setLoading(true)
      read(documentId, controller.signal).catch((failure) => {
        if (!controller.signal.aborted) setError(failure)
      }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    }
    return () => { controller.abort(); mutation.current?.abort() }
  }, [documentId, reload, state.me?.user_id])

  useEffect(() => {
    const controller = new AbortController()
    setSettings(null)
    apiFetch("/trade/settings", { token, signal: controller.signal }).then((data) => {
      if (!controller.signal.aborted) { setSettings(data); setSettingsError("") }
    }).catch((failure) => {
      if (!controller.signal.aborted) setSettingsError(failure.message)
    })
    return () => controller.abort()
  }, [token])

  useEffect(() => {
    question.current?.focus()
  }, [screen])

  const savedId = resource?.document_id
  const savedRevision = resource?.revision
  const readPacking = useEffectEvent(async (id, signal) => {
    const view = await apiFetch(`${base}/${id}/packing-review`, { token, signal })
    if (!signal.aborted) setPacking(view)
  })
  useEffect(() => {
    const controller = new AbortController()
    setPacking(null)
    setPackingError("")
    setPackingLoading(Boolean(savedId))
    if (savedId) readPacking(savedId, controller.signal).catch((failure) => {
      if (!controller.signal.aborted) setPackingError(failure.message)
    }).finally(() => { if (!controller.signal.aborted) setPackingLoading(false) })
    return () => controller.abort()
  }, [savedId, savedRevision, packingReload])

  function edit(key) {
    setNotice("")
    if (proposal?.status === "pending") setModifying(true)
    setScreen({ key, fields: null })
  }

  function startManual() {
    const company = settings?.company ?? {}
    setDraft((previous) => ({ ...previous, seller: {
      ...Object.fromEntries(["address", "contact", "phone", "email", "registration_details"].map((key) => [key, previous.seller[key] || company[key] || ""])),
      legal_name: previous.seller.legal_name || company.legal_name_en || company.company_name || "",
    } }))
    setGuided(false)
    edit("buyer")
  }

  function next() {
    if (following.key === "review" && (!resource || dirty || modifying)) save()
    else setScreen(following)
  }

  async function perform(work, success) {
    if (mutation.current) return
    const controller = new AbortController()
    mutation.current = controller
    setBusy(true)
    setError(null)
    setNotice("")
    try {
      const result = await work(controller.signal)
      if (!controller.signal.aborted) success?.(result)
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure)
    } finally {
      if (mutation.current === controller) {
        mutation.current = null
        setBusy(false)
      }
    }
  }

  function save() {
    perform(async (signal) => {
      if (modifying) {
        const review = await apiFetch(`${base}/${resource.document_id}/reviews/${proposal.id}/decisions`, {
          token, signal, method: "POST", body: { action: "modify", revision: proposal.revision,
            content_hash: proposal.content_hash, document: plPayload(draft) } })
        if (review.document_type) return { document: review, review: null }
        const document = await apiFetch(`${base}/${resource.document_id}`, { token, signal })
        return { document, review }
      }
      const document = await apiFetch(resource ? `${base}/${resource.document_id}` : base, {
        token, signal, method: resource ? "PUT" : "POST",
        body: resource ? { revision: resource.revision, document: plPayload(draft) } : plPayload(draft) })
      return { document, review: null }
    }, ({ document, review }) => {
      accept(document, review)
      if (!documentId) navigate(`/trade/pl/${document.document_id}`, { replace: true })
      else setNotice("저장했어요. 원본·계산 합계와 전체 내용을 확인해 주세요.")
    })
  }

  function decidePacking(action) {
    if (!packing || dirty || modifying || packing.revision !== resource.revision) return
    perform((signal) => apiFetch(`${base}/${resource.document_id}/packing-review/decisions`, {
      token, signal, method: "POST", body: { action, revision: packing.revision, content_hash: packing.content_hash },
    }), (document) => {
      accept(document)
      setNotice(action === "approve" ? "포장 합계를 승인했습니다. 새 버전에서 남은 항목을 확인한 뒤 별도로 최종 검토를 만들어 주세요." : "합계 승인을 취소했습니다. 원본 합계와 새 버전을 확인해 주세요.")
      setPackingReload((value) => value + 1)
    })
  }

  function propose() {
    perform((signal) => apiFetch(`${base}/${resource.document_id}/reviews`, { token, signal,
      method: "POST", body: { revision: resource.revision, formats } }), (review) => {
      setProposal(review)
      setScreen({ key: "review", fields: null })
      setNotice("최종 검토를 만들었습니다. 회사·직인과 포장 내용을 확인하고 선택해 주세요.")
    })
  }

  function decide(action) {
    perform(async (signal) => {
      const review = await apiFetch(`${base}/${resource.document_id}/reviews/${proposal.id}/decisions`, {
        token, signal, method: "POST", body: { action, revision: proposal.revision, content_hash: proposal.content_hash } })
      const document = await apiFetch(`${base}/${resource.document_id}`, { token, signal })
      return { document, review }
    }, ({ document, review }) => {
      accept(document, review)
      setNotice(action === "approve" ? "파일을 발급했습니다. 아래에서 다운로드하세요. 메일은 발송하지 않았습니다." : "검토를 취소했습니다. 내용을 저장한 뒤 다시 검토할 수 있습니다.")
    })
  }

  const current = resource && String(resource.document_id) === documentId ? resource : null
  const pending = proposal?.status === "pending"
  const canEdit = !busy && !loading && (!documentId || current)
  const stepIndex = PL_STEPS.findIndex((entry) => entry.key === screen.key)
  const step = PL_STEPS[stepIndex]
  const following = guided ? plNextScreen(draft, stepIndex)
    : { key: PL_STEPS[stepIndex + 1]?.key ?? "review", fields: null }
  const finalReview = proposal && ["pending", "approved"].includes(proposal.status) && !modifying && !dirty
  const missing = plMissing(draft)
  const remaining = PL_STEPS.filter((entry) => missing.some((path) => plSectionFor(path) === entry.key))
  return <div className="pi-workspace">
    <div className="page-head"><div><h1 className="page-title">PL 작성</h1><p className="page-sub">거래 내용을 채우고, 마지막에 전체를 확인해요.</p></div><Link className="btn" to="/">문서 종류 선택</Link></div>
    <div className="editor-toolbar"><span className="document-status">{current ? `${STATUS[current.status] ?? current.status} · 버전 ${current.revision}` : "새 PL"}</span>
      {documentId && <button type="button" className="btn" disabled={busy || loading} onClick={() => setReload((value) => value + 1)}>최신본 다시 읽기</button>}
    </div>
    {error && <div className="settings-load-error" role="alert"><p>{error.status === 401 ? "로그인 확인이 필요합니다. 입력 내용을 별도로 보관한 뒤 다시 로그인해 주세요." : error.message}</p>
      {error.status === 409 && <p>최신본을 다시 읽고 새로 검토해 주세요. 다시 읽으면 현재 입력을 교체하므로, 필요한 내용은 먼저 복사해 두세요.</p>}</div>}
    {notice && <p className="form-success" role="status">{notice}</p>}
    {loading && <p role="status">PL와 검토 내용을 불러오는 중입니다…</p>}
    {!loading && (!documentId || current) && <>
      {!["start", "source"].includes(screen.key) && <nav className="pi-progress" aria-label="PL 작성 단계"><ol>
        {PL_STEPS.map((entry) => <li key={entry.key}><button type="button" aria-current={entry.key === screen.key ? "step" : undefined}
          disabled={!canEdit} onClick={() => edit(entry.key)}>{entry.label}</button></li>)}
        <li><button type="button" aria-current={screen.key === "review" ? "step" : undefined} disabled={!canEdit || !current || dirty || modifying}
          onClick={() => setScreen({ key: "review", fields: null })}>전체 확인</button></li>
      </ol></nav>}
      <div className={`pi-editor${["start", "source"].includes(screen.key) ? " pi-intro" : ""}`}>
      <div className="pi-main">
      {screen.key === "start" && <section className="pi-question">
        <h2 tabIndex={-1} ref={question}>PL를 어떻게 작성할까요?</h2>
        <p className="pi-question-note">원문이 있으면 빠진 정보만 채우면 돼요.</p>
        <div className="pi-entry-options">
          <button type="button" disabled={!canEdit || dirty} onClick={() => setScreen({ key: "source", fields: null })}><strong>원문 붙여넣기</strong><span>메일·메모에서 거래 정보를 가져와요.</span><b aria-hidden="true">→</b></button>
          <button type="button" disabled={!canEdit} onClick={startManual}><strong>{dirty ? "이어서 직접 작성" : "직접 작성"}</strong><span>거래처부터 하나씩 입력해요.</span><b aria-hidden="true">→</b></button>
        </div>
        <p className="section-note">내용 확인과 승인 후에만 파일을 발급해요.</p>
      </section>}
      {screen.key === "source" && <><button className="pi-text-button" type="button" disabled={busy} onClick={() => setScreen({ key: "start", fields: null })}>← 작성 방법 선택</button>
      <AIInput kind="PL" token={token} disabled={busy} headingRef={question} onExtract={(text) => perform((signal) => apiFetch(`${base}/extract`, {
        token, signal, method: "POST", body: { text } }), (document) => {
        setGuided(true)
        accept(document, null, plNextScreen(plDraft(document.input)))
        navigate(`/trade/pl/${document.document_id}`)
      })} /></>}
      {step && <form className="pi-question" aria-label="PL 입력" onSubmit={(event) => { event.preventDefault(); if (canEdit) next() }}>
        <h2 tabIndex={-1} ref={question}>{step.question}</h2>
        <p className="pi-question-note">{screen.fields ? "이미 채워진 내용은 보관했어요. 아래 빈칸만 알려주세요." : step.note}</p>
        {screen.fields && <button className="pi-text-button" type="button" disabled={!canEdit} onClick={() => edit(step.key)}>이 단계 전체 수정</button>}
        {dirty && <p className="unsaved" role="status">저장 전 변경사항이 있어요.</p>}
        {current?.status === "issued" && <p className="section-note">수정 저장하면 새 버전으로 바뀝니다. 이미 발급된 파일은 그대로 보존합니다.</p>}
        <PLForm key={`${step.key}-${screen.fields ? "missing" : "all"}`} draft={draft} setDraft={setDraft} step={step.key} fields={screen.fields} settings={settings}
          missing={current?.missing_fields} disabled={!canEdit} onDirty={() => setDirty(true)} onShowAll={() => { if (screen.fields) edit(step.key) }} />
        <div className="pi-step-actions">
          <button className="btn" type="button" disabled={!canEdit} onClick={() => {
            if (stepIndex > 0) edit(PL_STEPS[stepIndex - 1].key)
            else if (current) setScreen({ key: "review", fields: null })
            else setScreen({ key: "start", fields: null })
          }}>이전</button>
          <button className="btn" type="button" disabled={!canEdit || (current && !dirty && !modifying)} onClick={save}>임시 저장</button>
          <button className="btn blue" type="submit" disabled={!canEdit}>{busy ? "처리 중…" : following.key === "review" ? "저장하고 전체 확인" : "다음"}</button>
        </div>
      </form>}
      {screen.key === "review" && current && (finalReview ? <ReviewPanel kind="pl" proposal={proposal} token={token} busy={busy} dirty={dirty} modifying={modifying} headingRef={question}
        onDecision={decide} onModify={() => edit("buyer")}
        onDownload={(file) => perform((signal) => downloadFile(file, token, signal), () => setNotice("파일 다운로드를 요청했습니다."))} />
      : <section className="pi-question" aria-label="서버 계산 결과"><h2 tabIndex={-1} ref={question}>전체 내용을 확인해 주세요</h2>
        <p className="pi-question-note">포장 합계 승인과 파일 발급 승인은 별개예요. 원본·계산 합계와 선적 조건을 확인하세요.</p>
        {dirty && <p className="form-error">아직 저장하지 않은 변경사항이 있어요. 저장한 뒤 검토해 주세요.</p>}
        {remaining.length > 0 && <div className="pi-missing"><p>아직 입력할 내용이 있어요.</p>{remaining.map((entry) =>
          <button key={entry.key} type="button" className="btn" disabled={!canEdit} onClick={() => setScreen({ key: entry.key, fields: missing.filter((path) => plSectionFor(path) === entry.key) })}>{entry.label} 보완</button>)}</div>}
        {current.issues.length > 0 && <ul className="document-issues" role="alert">{current.issues.map((issue,index) => <li key={index}>{issue.message}</li>)}</ul>}
        {current.status === "needs_input" && <p className="section-note">표시된 항목을 수정한 뒤 다시 저장해 주세요. 발행 회사·직인은 <Link to="/settings">회사 설정</Link>에서 확인할 수 있어요.</p>}
        <DocumentSnapshot kind="pl" document={current.document} />
        {packingError && <p className="form-error" role="alert">{packingError}</p>}
        {packingLoading && <p role="status">현재 버전의 포장 합계를 읽는 중입니다…</p>}
        <PackingReview view={packing} current={current} dirty={dirty || modifying} disabled={busy || packingLoading}
          onReload={() => setPackingReload((value) => value + 1)} onDecision={decidePacking} onEdit={() => edit("packing")} />
        <fieldset className="editor-checks" disabled={busy || pending || current.status !== "ready"}><legend>발급 형식</legend>{["pdf","xlsx"].map((format) => <label key={format}><input type="checkbox" checked={formats.includes(format)} onChange={(event) => setFormats((previous) => event.target.checked ? [...previous, format] : previous.filter((value) => value !== format))} /> {format.toUpperCase()}</label>)}</fieldset>
        <div className="form-actions">{(dirty || modifying) && <button className="btn" type="button" disabled={!canEdit} onClick={() => accept(current, proposal)}>저장 전 수정 취소</button>}
          <button className="btn" type="button" disabled={!canEdit || (!dirty && !modifying)} onClick={save}>{modifying ? "수정 저장·재검토" : "변경사항 저장"}</button>
          <button className="btn blue" type="button" disabled={busy || dirty || modifying || pending || current.status !== "ready" || !current.document.packing_totals?.approved || !formats.length} onClick={propose}>최종 검토 만들기</button></div>
      </section>)}
      {settingsError && <p className="section-note" role="status">기본 설정을 가져오지 못했어요. 직접 입력할 수 있습니다. {settingsError}</p>}
      </div>
      {!["start", "source"].includes(screen.key) && <PLSummary draft={draft} current={current} dirty={dirty} disabled={!canEdit} onEdit={edit} />}
      </div>
    </>}
  </div>
}

function PLSummary({ draft, current, dirty, disabled, onEdit }) {
  const [open, setOpen] = useState(false)
  const summaries = {
    buyer: draft.buyer.legal_name || "거래처 미입력",
    seller: draft.seller.legal_name || "판매자 미입력",
    packing: `${draft.items.length}개 품목 · 별도 포장 ${draft.packages.length}행`,
    terms: [draft.shipment_reference, draft.incoterms].filter(Boolean).join(" · ") || "선적 조건 미입력",
  }
  const totals = current?.document.packing_totals

  return <aside className="pi-summary" aria-label="작성 내용 요약">
    <button type="button" className="pi-summary-toggle" aria-expanded={open} aria-controls="pi-summary-content" onClick={() => setOpen(!open)}>작성 내용 {open ? "접기" : "보기"}</button>
    <div id="pi-summary-content" className={open ? "open" : ""}>
      <h2>작성 중인 PL</h2><p className="pi-summary-number">{draft.document_number || "문서번호 미입력"}</p>
      <dl>{PL_STEPS.map((step) => <div key={step.key}><dt>{step.label}<button type="button" disabled={disabled} onClick={() => { setOpen(false); onEdit(step.key) }}>{step.label} 수정</button></dt><dd>{summaries[step.key]}</dd></div>)}</dl>
      {totals && <div className="pi-summary-total"><span>{dirty ? "마지막 저장 포장 합계" : "서버 포장 합계"}</span>
        <strong>{totals.calculated.package_count ?? "확인 필요"}</strong>
        <span>순중량 {totals.calculated.net_weight_kg ?? "—"} kg · 총중량 {totals.calculated.gross_weight_kg ?? "—"} kg</span>
        <span>부피 {totals.calculated.volume_cbm ?? "—"} CBM</span>
        {Object.entries(totals.quantities).map(([unit,value]) => <span key={unit}>{value} {unit}</span>)}
        <span>{totals.approved ? "합계 승인 완료" : "합계 승인 필요"}</span></div>}
      <p className="section-note">{dirty ? "변경한 내용은 저장하고 포장 합계를 다시 확인해요." : "전체 확인 후 승인한 내용으로 파일을 발급해요."}</p>
    </div>
  </aside>
}
