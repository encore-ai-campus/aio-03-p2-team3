import { useEffect, useEffectEvent, useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { apiFetch, downloadFile } from "../api"
import { useAuth } from "../useAuth"
import CIForm from "../trade/CIForm"
import CISourcePicker from "../trade/CISourcePicker"
import DocumentSnapshot from "../trade/DocumentSnapshot"
import ReviewPanel from "../trade/ReviewPanel"
import { canCreateCI, ciDraft, ciMissing, ciPayload, emptyCI, piFieldLabel, sourceLabel } from "../trade/ci-input"

const STATUS = { needs_input: "입력 필요", ready: "검토 가능", issued: "발급 완료" }

export default function CIPage() {
  const { state } = useAuth()
  const token = state.accessToken
  const owner = state.me?.user_id
  const { documentId } = useParams()
  const navigate = useNavigate()
  const [resource, setResource] = useState(null)
  const [draft, setDraft] = useState(emptyCI)
  const [source, setSource] = useState(null)
  const [original, setOriginal] = useState(null)
  const [proposal, setProposal] = useState(null)
  const [formats, setFormats] = useState(["pdf", "xlsx"])
  const [screen, setScreen] = useState("start")
  const [dirty, setDirty] = useState(false)
  const [modifying, setModifying] = useState(false)
  const [onlyMissing, setOnlyMissing] = useState(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(Boolean(documentId))
  const [reload, setReload] = useState(0)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState("")
  const mutation = useRef(null)
  const created = useRef(null)
  const question = useRef(null)
  const base = "/trade/ci"

  async function readSource(id, revision, signal) {
    const [page, document] = await Promise.all([
      apiFetch(`${base}/source-pis?source_pi_id=${id}&source_revision=${revision}`, { token, signal }),
      apiFetch(`/trade/pi/${id}/versions/${revision}`, { token, signal }),
    ])
    return { source: { ...page.items[0], checked: true }, document }
  }

  function accept(document, review = null) {
    const saved = ciDraft(document.input)
    setResource(document)
    setDraft(saved)
    setProposal(review)
    if (review) setFormats(review.payload.formats)
    setDirty(false)
    setModifying(false)
    setOnlyMissing(null)
    setScreen("review")
  }

  const read = useEffectEvent(async (id, signal) => {
    const document = await apiFetch(`${base}/${id}`, { token, signal })
    if (document.input.mode === "standalone") { navigate(`/trade/ci/standalone/${id}`, { replace: true }); return }
    const review = document.proposal_id ? await apiFetch(`${base}/${id}/reviews/${document.proposal_id}`, { token, signal }) : null
    if (signal.aborted) return
    accept(document, review)
    const input = document.input
    if (!input.source_pi_id || !input.source_revision) { setScreen("source-pi"); return }
    const selected = await readSource(input.source_pi_id, input.source_revision, signal)
    if (!signal.aborted) { setSource(selected.source); setOriginal(selected.document) }
  })

  useEffect(() => {
    const controller = new AbortController()
    if (created.current && created.current.id === documentId && created.current.owner === owner) {
      created.current = null
      return () => { controller.abort(); mutation.current?.abort() }
    }
    mutation.current?.abort()
    mutation.current = null
    setBusy(false); setError(null); setNotice(""); setResource(null); setProposal(null)
    setSource(null); setOriginal(null); setDraft(emptyCI()); setDirty(false); setModifying(false)
    setOnlyMissing(null); setScreen("start")
    setLoading(Boolean(documentId))
    if (documentId) read(documentId, controller.signal).catch((failure) => {
      if (!controller.signal.aborted) setError(failure)
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => { controller.abort(); mutation.current?.abort() }
  }, [documentId, owner, reload])

  useEffect(() => { question.current?.focus() }, [screen])

  async function perform(work, success) {
    if (mutation.current) return
    const controller = new AbortController()
    mutation.current = controller
    setBusy(true); setError(null); setNotice("")
    try {
      const result = await work(controller.signal)
      if (!controller.signal.aborted) success?.(result)
    } catch (failure) {
      if (!controller.signal.aborted) {
        setError(failure)
        if (failure.code === "SOURCE_PI_NOT_APPROVED" || failure.code === "SOURCE_PI_NOT_FOUND") setSource((previous) => previous && ({ ...previous, checked: false }))
      }
    } finally {
      if (mutation.current === controller) { mutation.current = null; setBusy(false) }
    }
  }

  function selectSource(row) {
    if (resource?.input.source_pi_id && (resource.input.source_pi_id !== row.source_pi_id || resource.input.source_revision !== row.source_revision)) {
      setError({ code: "SOURCE_PI_CHANGE_REQUIRES_NEW_CI", message: "저장된 CI의 원본은 교체할 수 없습니다. 다른 PI 버전은 새 CI로 작성해 주세요." })
      return
    }
    setSource((previous) => previous && ({ ...previous, checked: false }))
    perform((signal) => readSource(row.source_pi_id, row.source_revision, signal), (result) => {
      setSource(result.source); setOriginal(result.document)
      setDraft((previous) => ({ ...previous, source_pi_id: row.source_pi_id, source_revision: row.source_revision }))
      if (resource && !resource.input.source_pi_id) setDirty(true)
    })
  }

  function refreshSource() {
    if (!draft.source_pi_id || !draft.source_revision) return
    selectSource({ source_pi_id: draft.source_pi_id, source_revision: draft.source_revision })
  }

  function editShipment() {
    if (proposal?.status === "pending") setModifying(true)
    setOnlyMissing(null); setScreen("shipment")
  }

  function save() {
    if (!canCreateCI(source, draft)) return
    perform(async (signal) => {
      if (modifying) {
        const review = await apiFetch(`${base}/${resource.document_id}/reviews/${proposal.id}/decisions`, {
          token, signal, method: "POST", body: { action: "modify", revision: proposal.revision,
            content_hash: proposal.content_hash, document: ciPayload(draft) } })
        if (review.document_type) return { document: review, review: null }
        return { document: await apiFetch(`${base}/${resource.document_id}`, { token, signal }), review }
      }
      const document = await apiFetch(resource ? `${base}/${resource.document_id}` : base, {
        token, signal, method: resource ? "PUT" : "POST",
        body: resource ? { revision: resource.revision, document: ciPayload(draft) } : ciPayload(draft) })
      return { document, review: null }
    }, ({ document, review }) => {
      accept(document, review)
      if (!documentId) {
        created.current = { id: String(document.document_id), owner }
        navigate(`/trade/ci/${document.document_id}`, { replace: true })
      }
      setNotice("CI를 서버에 저장했습니다. 선적 정보와 선택한 원본 버전을 확인해 주세요.")
    })
  }

  function propose() {
    if (!canCreateCI(source, draft)) return
    perform((signal) => apiFetch(`${base}/${resource.document_id}/reviews`, { token, signal, method: "POST",
      body: { revision: resource.revision, formats } }), (review) => { setProposal(review); setScreen("review") })
  }

  function decide(action) {
    perform(async (signal) => {
      const review = await apiFetch(`${base}/${resource.document_id}/reviews/${proposal.id}/decisions`, {
        token, signal, method: "POST", body: { action, revision: proposal.revision, content_hash: proposal.content_hash } })
      return { document: await apiFetch(`${base}/${resource.document_id}`, { token, signal }), review }
    }, ({ document, review }) => {
      accept(document, review)
      setNotice(action === "approve" ? "파일을 발급했습니다. 아래에서 다운로드하세요. 메일은 발송하지 않았습니다." : "검토를 취소했습니다. 다시 검토할 수 있습니다.")
    })
  }

  const current = resource && (!documentId || String(resource.document_id) === documentId) ? resource : null
  const canEdit = !busy && !loading && (!documentId || Boolean(current))
  const allowed = canCreateCI(source, draft)
  const finalReview = proposal && ["pending", "approved"].includes(proposal.status) && !modifying && !dirty
  const missing = ciMissing(draft)

  return <div className="pi-workspace">
    <div className="page-head"><div><h1 className="page-title">CI 작성</h1><p className="page-sub">거래 내용을 입력하거나 PI를 불러와 작성해요.</p></div><Link className="btn" to="/">문서 종류 선택</Link></div>
    <div className="editor-toolbar"><span className="document-status">{current ? `${STATUS[current.status] ?? current.status} · 버전 ${current.revision}` : "작성 중 · 서버 미저장"}</span>
      {documentId && <button className="btn" type="button" disabled={busy || loading} onClick={() => setReload((value) => value + 1)}>최신본 다시 읽기</button>}</div>
    {error && <div className="settings-load-error" role="alert"><p>{error.message}</p>
      {error.status === 409 && <p>입력은 보존했습니다. PI 상태를 다시 확인하거나 최신 CI를 다시 읽고 재검토해 주세요. 최신 CI를 읽으면 현재 입력을 교체하므로 필요한 내용은 먼저 복사해 두세요.</p>}
      {error.code === "SOURCE_PI_CHANGE_REQUIRES_NEW_CI" && <Link to="/trade/ci">새 CI 작성</Link>}</div>}
    {notice && <p className="form-success" role="status">{notice}</p>}
    {loading && <p role="status">CI와 원본 버전을 읽는 중입니다…</p>}
    {!loading && (!documentId || current) && <>
      {screen !== "start" && <nav className="pi-progress" aria-label="CI 작성 단계"><ol>
        <li><button type="button" aria-current={screen === "source-pi" ? "step" : undefined} disabled={!canEdit} onClick={() => setScreen("source-pi")}>원본 PI</button></li>
        <li><button type="button" aria-current={screen === "shipment" ? "step" : undefined} disabled={!canEdit || !source} onClick={editShipment}>선적 정보</button></li>
        <li><button type="button" aria-current={screen === "review" ? "step" : undefined} disabled={!canEdit || !current || dirty || modifying} onClick={() => setScreen("review")}>전체 확인</button></li>
      </ol></nav>}
      <div className={`pi-editor${screen === "start" ? " pi-intro" : ""}`}><div className="pi-main">
        {screen === "start" && <section className="pi-question"><h2 tabIndex={-1} ref={question}>CI를 어떻게 작성할까요?</h2>
          <p className="pi-question-note">작성 방법을 선택해 주세요.</p>
          <div className="pi-entry-options">
            <button type="button" disabled={!canEdit} onClick={() => navigate("/trade/ci/standalone", { state: { source: true } })}><strong>원문 붙여넣기</strong><span>메일·메모에서 거래 정보를 가져와요.</span><b aria-hidden="true">→</b></button>
            <button type="button" disabled={!canEdit} onClick={() => navigate("/trade/ci/standalone")}><strong>직접 작성</strong><span>거래 내용을 하나씩 입력해요.</span><b aria-hidden="true">→</b></button>
            <button type="button" disabled={!canEdit} onClick={() => setScreen("source-pi")}><strong>PI 문서 불러오기</strong><span>기존 PI를 선택하고 선적 정보를 입력해요.</span><b aria-hidden="true">→</b></button>
          </div></section>}
        {source && <section className={source.approved && source.checked ? "pi-missing" : "settings-load-error"} role={source.approved && source.checked ? "status" : "alert"} aria-label="원본 PI 남은 작업">
          <p><strong>PI {source.source_pi_id} · 버전 {source.source_revision} · {sourceLabel(source)}</strong></p>
          {!source.checked && <p>원본 PI 상태를 다시 확인해 주세요. 확인 전에는 서버에 CI를 생성하지 않습니다.</p>}
          {!source.approved && <><ul>{source.missing_fields.map((path) => <li key={path}>{piFieldLabel(path)} 보완</li>)}{source.issues.map((issue,index) => <li key={index}>{issue.message}</li>)}<li>PI 최종 검토 후 ‘승인하고 파일 발급’ 완료</li></ul>
            {source.current_revision !== source.source_revision && <p>현재 PI는 버전 {source.current_revision}입니다. 현재 버전을 보완·승인한 뒤 목록에서 새 버전을 직접 선택해 주세요.</p>}
            <Link className="btn" to={`/trade/pi/${source.source_pi_id}`} target="_blank" rel="noopener noreferrer">PI 보완·승인하기 ↗</Link></>}
          <button className="btn" type="button" disabled={!canEdit} onClick={refreshSource}>PI 상태 다시 확인</button>
        </section>}
        {screen === "source-pi" && <section className="pi-question"><h2 tabIndex={-1} ref={question}>어떤 PI로 만들까요?</h2>
          {current?.input.source_pi_id ? <p className="section-note">저장된 CI의 원본은 고정됩니다. 다른 버전은 <Link to="/trade/ci">새 CI로 작성</Link>해 주세요.</p>
            : <CISourcePicker token={token} selected={source} disabled={!canEdit} onSelect={selectSource} />}
          <div className="pi-step-actions"><button className="btn" type="button" disabled={!canEdit} onClick={() => setScreen(current ? "review" : "start")}>이전</button>
            <button className="btn blue" type="button" disabled={!canEdit || !source?.checked} onClick={editShipment}>선적 정보 입력</button></div></section>}
        {screen === "shipment" && <section className="pi-question"><h2 tabIndex={-1} ref={question}>선적 정보를 알려주세요</h2>
          <p className="pi-question-note">{onlyMissing ? "미리 입력한 값은 보관했어요. 아래 빈칸만 채워 주세요." : "거래 사실은 원본에서 보존하고 선적 정보만 보완해요."}</p>
          {onlyMissing && <button className="pi-text-button" type="button" disabled={!canEdit} onClick={() => setOnlyMissing(null)}>이 단계 전체 수정</button>}
          {!current && <p className="section-note">아직 서버에 저장되지 않았습니다. PI 보완 탭을 열어도 이 화면의 입력은 유지됩니다. 이 탭을 새로고침하거나 닫으면 미저장 입력은 사라집니다.</p>}
          {dirty && <p className="unsaved" role="status">저장 전 변경사항이 있어요.</p>}
          <CIForm draft={draft} setDraft={setDraft} disabled={!canEdit} missing={onlyMissing ?? current?.missing_fields ?? []} onlyMissing={Boolean(onlyMissing)}
            onDirty={() => setDirty(true)} />
          <div className="pi-step-actions"><button className="btn" type="button" disabled={!canEdit} onClick={() => setScreen("source-pi")}>이전</button>
            <button className="btn blue" type="button" disabled={!canEdit || !allowed || (current && !dirty && !modifying)} onClick={() => save()}>{current ? modifying ? "수정 저장·재검토" : "저장하고 전체 확인" : "CI 생성"}</button></div>
          {!allowed && <p className="section-note">선적 정보는 미리 입력할 수 있습니다. 선택한 PI를 보완·승인하고 상태를 다시 확인하면 CI 생성이 가능합니다.</p>}
        </section>}
        {screen === "review" && current && (finalReview ? <ReviewPanel kind="ci" proposal={proposal} token={token} busy={busy} dirty={dirty} modifying={modifying} headingRef={question}
          onDecision={decide} onModify={editShipment} onDownload={(file) => perform((signal) => downloadFile(file, token, signal), () => setNotice("파일 다운로드를 요청했습니다."))} />
          : <section className="pi-question"><h2 tabIndex={-1} ref={question}>전체 내용을 확인해 주세요</h2>
            <p className="pi-question-note">원본 PI의 승인 버전·거래가격·출하 수량·FOC와 선적 정보를 확인하세요.</p>
            {dirty && <p className="form-error">보존한 변경사항을 먼저 저장한 뒤 검토해 주세요.</p>}
            {missing.length > 0 && <div className="pi-missing"><p>아직 입력할 내용이 있어요.</p><button className="btn" type="button" disabled={!canEdit} onClick={() => { setOnlyMissing(missing); setScreen("shipment") }}>선적 정보 보완</button></div>}
            {current.issues.length > 0 && <ul className="document-issues" role="alert">{current.issues.map((issue,index) => <li key={index}>{issue.message}</li>)}</ul>}
            <DocumentSnapshot kind="ci" document={current.document} />
            <fieldset className="editor-checks" disabled={busy || current.status !== "ready"}><legend>발급 형식</legend>{["pdf","xlsx"].map((format) => <label key={format}><input type="checkbox" checked={formats.includes(format)} onChange={(event) => setFormats((previous) => event.target.checked ? [...previous,format] : previous.filter((value) => value !== format))} /> {format.toUpperCase()}</label>)}</fieldset>
            <div className="form-actions"><button className="btn" type="button" disabled={!canEdit} onClick={editShipment}>선적 정보 수정</button>
              <button className="btn blue" type="button" disabled={!canEdit || !allowed || dirty || modifying || current.status !== "ready" || !formats.length || proposal?.status === "pending"} onClick={propose}>최종 검토 만들기</button></div>
          </section>)}
      </div>{screen !== "start" && <CISummary source={source} original={original} draft={draft} />}</div>
    </>}
  </div>
}

function CISummary({ source, original, draft }) {
  const [open, setOpen] = useState(false)
  return <aside className="pi-summary" aria-label="작성 내용 요약"><button className="pi-summary-toggle" type="button" aria-expanded={open} aria-controls="ci-summary" onClick={() => setOpen(!open)}>작성 내용 {open ? "접기" : "보기"}</button>
    <div id="ci-summary" className={open ? "open" : ""}><h2>작성 중인 CI</h2><p className="pi-summary-number">{draft.document_number || "문서번호 미입력"}</p>
      <dl><div><dt>원본 PI</dt><dd>{source ? `${source.document_number || source.source_pi_id} · 버전 ${source.source_revision}` : "선택 필요"}</dd></div>
        <div><dt>구매자</dt><dd>{original?.buyer?.legal_name || "—"}</dd></div><div><dt>판매자</dt><dd>{original?.seller?.legal_name || "—"}</dd></div>
        <div><dt>원본 품목·유상/FOC 수량</dt><dd>{original?.items?.map((row,index) => <div key={index}>{row.product_name} · {row.paid_quantity ?? row.quantity ?? "—"} / {row.free_quantity ?? "—"} {row.unit} · {row.unit_price ?? "미확정"}</div>) || "—"}</dd></div>
        <div><dt>선적 참조</dt><dd>{draft.shipment_reference || "미입력"}</dd></div></dl>
      {source && <div className="pi-summary-total"><span>선택한 PI 버전의 합계</span><strong>{source.currency} {source.total ?? "미확정"}</strong></div>}
      <p className="section-note">PI 승인 전에는 작성 준비만 가능합니다. 거래 사실은 선택한 승인 버전으로 고정됩니다.</p>
    </div></aside>
}
