import { useEffect, useRef, useState } from "react"
import { apiFetch } from "../api"
import { useAuth } from "../useAuth"
import BankSettings from "../settings/BankSettings"
import BrandingSettings from "../settings/BrandingSettings"
import CompanySettings from "../settings/CompanySettings"
import CounterpartySettings from "../settings/CounterpartySettings"
import PriceSettings from "../settings/PriceSettings"

const SECTIONS = [
  ["company", "회사 정보", "문서에 표시할 발행자 정보를 입력하세요."],
  ["counterparties", "거래처", "반복해서 사용하는 거래처와 배송지를 관리합니다."],
  ["sale", "판매 단가표", "PI에 사용할 판매 단가를 관리합니다."],
  ["purchase", "구매 단가표", "PO에 사용할 매입 단가를 관리합니다."],
  ["banks", "은행 계좌", "문서 통화에 맞는 수취 계좌를 등록합니다."],
  ["branding", "로고·직인", "비공개 저장소에 회사 이미지를 보관합니다."],
]

export default function SettingsPage() {
  const { state, retry: retryLogin } = useAuth()
  const token = state.accessToken
  const [section, setSection] = useState("company")
  const [read, setRead] = useState({ phase: "loading", data: null, error: "" })
  const [reload, setReload] = useState(0)
  const [saveState, setSaveState] = useState({ saving: false, error: "", notice: "" })
  const mutation = useRef(null)

  useEffect(() => {
    const controller = new AbortController()
    setRead((previous) => ({ ...previous, phase: "loading", error: "" }))
    apiFetch("/trade/settings", { token, signal: controller.signal }).then((data) => {
      if (!controller.signal.aborted) setRead({ phase: "ready", data, error: "" })
    }).catch((error) => {
      if (!controller.signal.aborted) setRead((previous) => ({ ...previous, phase: "error", error: error.message }))
    })
    return () => controller.abort()
  }, [token, reload])

  useEffect(() => () => mutation.current?.abort(), [])

  async function save(path, body, method = "PUT") {
    if (mutation.current) return null
    const controller = new AbortController()
    mutation.current = controller
    setSaveState({ saving: true, error: "", notice: "" })
    try {
      const data = await apiFetch(`/trade/settings${path}`, { method, token, body, signal: controller.signal })
      if (controller.signal.aborted) return null
      setRead({ phase: "ready", data, error: "" })
      setSaveState({ saving: false, error: "", notice: "저장했습니다. 새 문서·검토부터 적용됩니다." })
      return data
    } catch (error) {
      if (!controller.signal.aborted) setSaveState({ saving: false, notice: "", error: error.status === 401
        ? "로그인 확인이 필요합니다. 입력 내용을 확인한 뒤 로그인 상태를 다시 확인해 주세요."
        : error.message })
      return null
    } finally {
      if (mutation.current === controller) mutation.current = null
    }
  }

  const [, title, note] = SECTIONS.find(([key]) => key === section)
  const props = { data: read.data, save, ...saveState, saving: saveState.saving || read.phase !== "ready",
    clearStatus: () => setSaveState({ saving: false, error: "", notice: "" }) }
  return (
    <>
      <div className="page-head"><div><h1 className="page-title">설정</h1><p className="page-sub">회사와 거래에 필요한 기준 정보를 관리합니다.</p></div></div>
      {read.error && <div className="settings-load-error" role="alert"><p>{read.error}</p>
        <button className="btn" type="button" onClick={() => setReload((value) => value + 1)}>다시 읽기</button>
        <button className="btn" type="button" onClick={retryLogin}>로그인 상태 확인</button>
      </div>}
      {!read.data ? (read.phase === "loading" && <p role="status">설정을 불러오는 중입니다…</p>) : (
        <div className="settings-layout">
          <nav className="settings-nav" aria-label="설정 항목">
            {SECTIONS.map(([key, label]) => <button key={key} type="button" className={key === section ? "active" : ""}
              aria-pressed={key === section} disabled={saveState.saving} onClick={() => {
                setSection(key)
                setSaveState({ saving: false, error: "", notice: "" })
              }}>{label}</button>)}
          </nav>
          <section className="card settings-panel" aria-label={title}>
            <div className="panel-head"><div><h2 className="section-title">{title}</h2><p className="section-note">{note}</p></div></div>
            {section === "company" && <CompanySettings {...props} />}
            {section === "counterparties" && <CounterpartySettings {...props} />}
            {(section === "sale" || section === "purchase") && <PriceSettings key={section} role={section} {...props} />}
            {section === "banks" && <BankSettings {...props} />}
            {section === "branding" && <BrandingSettings token={token} {...props} />}
            {saveState.error && <button className="link-button" type="button" onClick={retryLogin}>로그인 상태 다시 확인</button>}
          </section>
        </div>
      )}
    </>
  )
}
