import { useEffect, useEffectEvent, useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { apiFetch, downloadFile } from "../api"
import { useAuth } from "../useAuth"
import AIInput from "../trade/AIInput"
import DocumentSnapshot from "../trade/DocumentSnapshot"
import PIForm from "../trade/PIForm"
import { emptyPI, PI_STEPS, piDraft, piNextScreen, piPayload } from "../trade/pi-input"
import ReviewPanel from "../trade/ReviewPanel"
import RenderFailureHelp from "../trade/RenderFailureHelp"
import MissingFieldsDialog, { updateMissingField } from "../trade/MissingFieldsDialog"

const STATUS = { needs_input: "입력 필요", ready: "검토 가능", issued: "발급 완료" }

export default function PIPage() {
  const { state } = useAuth()
  const token = state.accessToken
  const { documentId } = useParams()
  const navigate = useNavigate()
  const [resource, setResource] = useState(null)
  const [draft, setDraft] = useState(emptyPI)
  const [proposal, setProposal] = useState(null)
  const [formats, setFormats] = useState(["pdf", "xlsx"])
  const [dirty, setDirty] = useState(false)
  const [modifying, setModifying] = useState(false)
  const [loading, setLoading] = useState(Boolean(documentId))
  const [reload, setReload] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState("")
  const [previousFiles, setPreviousFiles] = useState([])
  const [screen, setScreen] = useState({ key: "start", fields: null })
  const [guided, setGuided] = useState(false)
  const [settings, setSettings] = useState(null)
  const [settingsError, setSettingsError] = useState("")
  const [sourceText, setSourceText] = useState("")
  const errorBox = useRef(null)
  const question = useRef(null)
  const mutation = useRef(null)
  const base = "/trade/pi"

  function accept(document, review = null, next = { key: "review", fields: null }) {
    setResource(document)
    setDraft(piDraft(document.input))
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
      accept(document, review, document.status === "needs_input" ? piNextScreen(piDraft(document.input)) : undefined)
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
    setPreviousFiles([])
    setModifying(false)
    setDirty(false)
    if (!documentId) {
      setSourceText("")
      setDraft(emptyPI())
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
  }, [documentId, reload])

  useEffect(() => {
    const controller = new AbortController()
    apiFetch("/trade/settings", { token, signal: controller.signal }).then((data) => {
      if (!controller.signal.aborted) {
        setSettings(data); setSettingsError("")
        if (!documentId) setDraft((previous) => ({ ...previous, seller: { ...previous.seller,
          legal_name: data.company?.legal_name_en || data.company?.company_name || "", address: data.company?.address || "" } }))
      }
    }).catch((failure) => {
      if (!controller.signal.aborted) setSettingsError(failure.message)
    })
    return () => controller.abort()
  }, [token, documentId])

  useEffect(() => {
    question.current?.focus()
  }, [screen])

  useEffect(() => {
    if (error) errorBox.current?.focus()
  }, [error])

  function edit(key) {
    setNotice("")
    if (proposal?.status === "pending") setModifying(true)
    const companyName = settings?.company?.legal_name_en || settings?.company?.company_name
    const companyAddress = settings?.company?.address || ""
    if (companyName && (draft.seller?.legal_name !== companyName || draft.seller?.address !== companyAddress)) {
      setDraft((previous) => ({ ...previous, seller: { ...previous.seller, legal_name: companyName, address: companyAddress } }))
      setDirty(true)
    }
    setScreen({ key, fields: null })
  }

  function startManual() {
    const company = settings?.company ?? {}
    const companyName = company.legal_name_en || company.company_name
    setDraft((previous) => ({ ...previous, seller: {
      ...Object.fromEntries(["contact", "phone", "email", "registration_details"].map((key) => [key, previous.seller[key] || company[key] || ""])),
      address: company.address || "",
      legal_name: companyName,
    } }))
    setGuided(false)
    setNotice("")
    setScreen({ key: "buyer", fields: null })
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
            content_hash: proposal.content_hash, document: piPayload(draft) } })
        if (review.document_type) return { document: review, review: null }
        const document = await apiFetch(`${base}/${resource.document_id}`, { token, signal })
        return { document, review }
      }
      const document = await apiFetch(resource ? `${base}/${resource.document_id}` : base, {
        token, signal, method: resource ? "PUT" : "POST",
        body: resource ? { revision: resource.revision, document: piPayload(draft) } : piPayload(draft) })
      return { document, review: null }
    }, ({ document, review }) => {
      accept(document, review)
      if (!documentId) navigate(`/trade/pi/${document.document_id}`, { replace: true })
      else setNotice("저장했어요. 계산된 금액과 전체 내용을 확인해 주세요.")
    })
  }

  function refreshSettings() {
    const files = resource.files ?? []
    perform((signal) => apiFetch(`${base}/${resource.document_id}/refresh-settings`, {
      token, signal, method: "POST", body: { revision: resource.revision } }), (document) => {
      accept(document)
      setPreviousFiles(files)
      setNotice("최신 설정 정보를 새 PI 버전에 적용했습니다. 내용을 확인하고 다시 검토해 주세요. 이미 발급된 파일은 보존됩니다.")
    })
  }
  function propose() {
    perform((signal) => apiFetch(`${base}/${resource.document_id}/reviews`, { token, signal,
      method: "POST", body: { revision: resource.revision, formats } }), (review) => {
      setProposal(review)
      setScreen({ key: "review", fields: null })
      setNotice("최종 검토를 만들었습니다. 회사·계좌·직인과 금액을 확인하고 선택해 주세요.")
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
  const issuerName = settings?.company?.legal_name_en || settings?.company?.company_name
  const issuerAddress = settings?.company?.address || ""
  useEffect(() => {
    if (current?.status === "needs_input" && !proposal && issuerName
        && (draft.seller?.legal_name !== issuerName || draft.seller?.address !== issuerAddress)) {
      setDraft((previous) => ({ ...previous, seller: { ...previous.seller, legal_name: issuerName, address: issuerAddress } }))
      setDirty(true)
    }
  }, [current?.document_id, current?.revision, current?.status, proposal, issuerName, issuerAddress, draft.seller?.legal_name, draft.seller?.address])
  const pending = proposal?.status === "pending"
  const canEdit = !busy && !loading && (!documentId || current)
  const reviewIssues = current?.issues?.length ? current.issues
    : (current?.document?.blocking_issues ?? []).map((message) => ({ code: "DOCUMENT_INVALID", message }))
  const hasVisibleIssues = [...(current?.missing_fields ?? []), ...reviewIssues.map((issue) => issue?.message ?? issue)]
    .some((issue) => String(issue).trim().toLowerCase() !== "document_number"
      && !/document number/i.test(String(issue).replace(/_/g, " ")))
  const canRecheck = current?.status === "needs_input" && !hasVisibleIssues
  const stepIndex = PI_STEPS.findIndex((entry) => entry.key === screen.key)
  const step = PI_STEPS[stepIndex]
  const following = guided ? piNextScreen(draft, stepIndex)
    : { key: PI_STEPS[stepIndex + 1]?.key ?? "review", fields: null }
  const finalReview = proposal && ["pending", "approved"].includes(proposal.status) && !modifying && !dirty
  const hasUnsupportedRemarks = /[ㄱ-ㅎㅏ-ㅣ가-힣]/.test(current?.document?.remarks ?? "")
  return <div className="pi-workspace">
    <div className="page-head"><div><h1 className="page-title">PI 작성</h1><p className="page-sub">거래 내용을 채우고, 마지막에 전체를 확인해요.</p></div><Link className="btn" to="/">문서 종류 선택</Link></div>
    <div className="editor-toolbar"><span className="document-status">{current ? `${STATUS[current.status] ?? current.status} · 버전 ${current.revision}` : "새 PI"}</span>
      {documentId && <button type="button" className="btn" disabled={busy || loading} onClick={() => setReload((value) => value + 1)}>최신본 다시 읽기</button>}
    </div>
    {error && <div className="settings-load-error" role="alert" tabIndex={-1} ref={errorBox}><p>{error.status === 401 ? "로그인 확인이 필요합니다. 입력 내용을 별도로 보관한 뒤 다시 로그인해 주세요." : error.message}</p>
      {error?.code === "RENDER_FAILED" && <RenderFailureHelp hasUnsupportedRemarks={hasUnsupportedRemarks} onEditTerms={() => { setError(null); edit("terms") }} />}
      {error.status === 409 && error.code !== "PI_NUMBER_DUPLICATE" && <p>최신본을 다시 읽고 새로 검토해 주세요. 다시 읽으면 현재 입력을 교체하므로, 필요한 내용은 먼저 복사해 두세요.</p>}</div>}
    {notice && <p className="form-success" role="status">{notice}</p>}
    {previousFiles.length > 0 && <section className="pi-question" aria-label="이전 발급 파일">
      <h2>설정 변경 전 발급 파일</h2><p className="section-note">이 파일은 기존 설정으로 발급된 그대로 보존됩니다.</p>
      <div className="form-actions">{previousFiles.map((file) => <button key={file.id} type="button" className="btn"
        disabled={busy} onClick={() => perform((signal) => downloadFile(file, token, signal), () => setNotice("이전 발급 파일 다운로드를 요청했습니다."))}>
        이전 {file.file_format.toUpperCase()} 다운로드</button>)}</div>
    </section>}
    {loading && <p role="status">PI와 검토 내용을 불러오는 중입니다…</p>}
    {!loading && (!documentId || current) && <>
      {!["start", "source"].includes(screen.key) && <nav className="pi-progress" aria-label="PI 작성 단계"><ol>
        {PI_STEPS.map((entry) => <li key={entry.key}><button type="button" aria-current={entry.key === screen.key ? "step" : undefined}
          disabled={!canEdit} onClick={() => edit(entry.key)}>{entry.label}</button></li>)}
        <li><button type="button" aria-current={screen.key === "review" ? "step" : undefined} disabled={!canEdit || !current || dirty || modifying}
          onClick={() => setScreen({ key: "review", fields: null })}>전체 확인</button></li>
      </ol></nav>}
      <div className={`pi-editor${["start", "source"].includes(screen.key) ? " pi-intro" : ""}`}>
      <div className="pi-main">
      {screen.key === "start" && <section className="pi-question">
        <h2 tabIndex={-1} ref={question}>PI를 어떻게 작성할까요?</h2>
        <p className="pi-question-note">원문이 있으면 빠진 정보만 채우면 돼요.</p>
        <div className="pi-entry-options">
          <button type="button" disabled={!canEdit || dirty} onClick={() => setScreen({ key: "source", fields: null })}><strong>원문 붙여넣기</strong><span>메일·메모에서 거래 정보를 가져와요.</span><b aria-hidden="true">→</b></button>
          <button type="button" disabled={!canEdit} onClick={startManual}><strong>{dirty ? "이어서 직접 작성" : "직접 작성"}</strong><span>거래처부터 하나씩 입력해요.</span><b aria-hidden="true">→</b></button>
        </div>
        <p className="section-note">내용 확인과 승인 후에만 파일을 발급해요.</p>
      </section>}
      {screen.key === "source" && <><button className="pi-text-button" type="button" disabled={busy} onClick={() => setScreen({ key: "start", fields: null })}>← 작성 방법 선택</button>
      <AIInput token={token} disabled={busy} headingRef={question} value={sourceText} onTextChange={setSourceText} onExtract={(text) => perform((signal) => apiFetch(`${base}/extract`, {
        token, signal, method: "POST", body: { text } }), (document) => {
        setGuided(true)
        accept(document, null, piNextScreen(piDraft(document.input)))
        navigate(`/trade/pi/${document.document_id}`)
      })} /></>}
      {step && <form className="pi-question" aria-label="PI 입력" onSubmit={(event) => { event.preventDefault(); if (canEdit) next() }}>
        <h2 tabIndex={-1} ref={question}>{step.question}</h2>
        <p className="pi-question-note">{screen.fields ? "이미 채워진 내용은 보관했어요. 아래 빈칸만 알려주세요." : step.note}</p>
        {screen.fields && <button className="pi-text-button" type="button" disabled={!canEdit} onClick={() => edit(step.key)}>이 단계 전체 수정</button>}
        {dirty && <p className="unsaved" role="status">저장 전 변경사항이 있어요.</p>}
        {current?.status === "issued" && <p className="section-note">수정 저장하면 새 버전으로 바뀝니다. 이미 발급된 파일은 그대로 보존합니다.</p>}
        <PIForm token={token} key={`${step.key}-${screen.fields ? "missing" : "all"}`} draft={draft} setDraft={setDraft} step={step.key} fields={screen.fields} settings={settings}
          missing={current?.missing_fields} disabled={!canEdit} onDirty={() => setDirty(true)} onShowAll={() => { if (screen.fields) edit(step.key) }} />
        <div className="pi-step-actions">
          <button className="btn" type="button" disabled={!canEdit} onClick={() => {
            if (stepIndex > 0) edit(PI_STEPS[stepIndex - 1].key)
            else if (current) setScreen({ key: "review", fields: null })
            else setScreen({ key: "start", fields: null })
          }}>이전</button>
          <button className="btn" type="button" disabled={!canEdit || (current && !dirty && !modifying)} onClick={save}>임시 저장</button>
          <button className="btn blue" type="submit" disabled={!canEdit}>{busy ? "처리 중…" : following.key === "review" ? "저장하고 전체 확인" : "다음"}</button>
        </div>
      </form>}
      {screen.key === "review" && current && (finalReview ? <ReviewPanel proposal={proposal} token={token} busy={busy} dirty={dirty} modifying={modifying} headingRef={question}
        onDecision={decide} onModify={() => edit("buyer")} onRefreshSettings={refreshSettings}
        onDownload={(file) => perform((signal) => downloadFile(file, token, signal), () => setNotice("파일 다운로드를 요청했습니다."))} />
      : <section className="pi-question" aria-label="서버 계산 결과"><h2 tabIndex={-1} ref={question}>전체 내용을 확인해 주세요</h2>
        <p className="pi-question-note">저장된 내용으로 계산한 금액이에요. 회사·계좌와 거래 조건을 함께 확인하세요.</p>
        {dirty && <p className="form-error">아직 저장하지 않은 변경사항이 있어요. 저장한 뒤 검토해 주세요.</p>}
        {current.status === "needs_input" && <p className="section-note">표시된 항목을 수정한 뒤 다시 저장해 주세요. 발행 회사·계좌·직인은 <Link to="/settings">회사 설정</Link>에서 확인할 수 있어요.</p>}
        {canRecheck && <p className="section-note">오류 항목은 없지만 서버 상태가 ‘입력 필요’입니다. 현재 저장된 값으로 다시 확인해 주세요.</p>}
        <DocumentSnapshot document={current.document} />
        <fieldset className="editor-checks" disabled={busy || pending || current.status !== "ready"}><legend>발급 형식</legend>{["pdf","xlsx"].map((format) => <label key={format}><input type="checkbox" checked={formats.includes(format)} onChange={(event) => setFormats((previous) => event.target.checked ? [...previous, format] : previous.filter((value) => value !== format))} /> {format.toUpperCase()}</label>)}</fieldset>
        <div className="form-actions">{(dirty || modifying) && <button className="btn" type="button" disabled={!canEdit} onClick={() => accept(current, proposal)}>저장 전 수정 취소</button>}
          {current && <button type="button" className="btn" title="최신 설정 정보를 새 PI 버전에 적용합니다. 이미 발급된 파일은 보존됩니다."
            disabled={busy || loading || ["sent", "sending"].includes(current.status)} onClick={refreshSettings}>최신 설정 정보 적용</button>}
          <button className="btn" type="button" disabled={!canEdit || (!dirty && !modifying && !canRecheck)} onClick={save}>{modifying ? "수정 저장·재검토" : canRecheck ? "문서 다시 확인" : "변경사항 저장"}</button>
          <button className="btn blue" type="button" disabled={busy || dirty || modifying || pending || current.status !== "ready" || !formats.length} onClick={propose}>최종 검토 만들기</button></div>
      </section>)}
      <MissingFieldsDialog open={Boolean(current && screen.key === "review" && !finalReview)} kind="PI" draft={draft} missing={current?.missing_fields} issues={reviewIssues} busy={busy} dirty={dirty}
        onChange={(path,value) => { setDraft((previous) => updateMissingField(previous,path,value)); setDirty(true); if (pending) setModifying(true) }}
        onSave={save} onOpenStep={edit} />
      {settingsError && <p className="section-note" role="status">회사 설정을 불러오지 못해 당사 회사명을 자동 적용할 수 없습니다. <Link to="/settings">설정 확인</Link> · {settingsError}</p>}
      </div>
      {!["start", "source"].includes(screen.key) && <PISummary draft={draft} current={current} dirty={dirty} disabled={!canEdit} onEdit={edit} />}
      </div>
    </>}
  </div>
}

function PISummary({ draft, current, dirty, disabled, onEdit }) {
  const [open, setOpen] = useState(false)
  const summaries = {
    buyer: draft.buyer.legal_name || "거래처 미입력",
    seller: draft.seller.legal_name || "판매자 미입력",
    items: draft.items.length ? `${draft.items.length}개 품목 · ${draft.currency || "통화 미선택"}` : "품목 미입력",
    terms: [draft.incoterms, draft.payment_terms].filter(Boolean).join(" · ") || "거래 조건 미입력",
  }
  return <aside className="pi-summary" aria-label="작성 내용 요약">
    <button type="button" className="pi-summary-toggle" aria-expanded={open} aria-controls="pi-summary-content" onClick={() => setOpen(!open)}>작성 내용 {open ? "접기" : "보기"}</button>
    <div id="pi-summary-content" className={open ? "open" : ""}>
      <h2>작성 중인 PI</h2><p className="pi-summary-number">{draft.document_number || "승인·발급 시 문서번호 자동 생성"}</p>
      <dl>{PI_STEPS.map((step) => <div key={step.key}><dt>{step.label}<button type="button" disabled={disabled} onClick={() => { setOpen(false); onEdit(step.key) }}>{step.label} 수정</button></dt><dd>{summaries[step.key]}</dd></div>)}</dl>
      {current && <div className="pi-summary-total"><span>{dirty ? "마지막 저장 금액" : "저장된 합계"}</span><strong>{current.document.currency} {current.document.total ?? "확인 필요"}</strong></div>}
      <p className="section-note">{dirty ? "변경한 내용은 저장하면 계산에 반영돼요." : "전체 확인 후 승인한 내용으로 파일을 발급해요."}</p>
    </div>
  </aside>
}
