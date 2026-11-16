import { useEffect, useRef, useState } from "react"
import { apiFetch } from "../api"
import { useAuth } from "../useAuth"

const CALLBACK_MESSAGES = {
  connected: "Google 동의를 마쳤습니다. 아래에서 현재 연결·감시 상태를 확인해 주세요.",
  cancelled: "Gmail 연결을 취소했습니다. 연결하려면 다시 시도해 주세요.",
  scope_missing: "Gmail 필수 권한이 누락되었습니다. 다시 연결하고 필요한 권한에 동의해 주세요.",
  different_account: "앱 로그인에 사용한 Google 계정과 다릅니다. 같은 계정으로 다시 연결해 주세요.",
  account_conflict: "이 Google 계정의 기존 자료와 충돌하여 연결하지 못했습니다. 관리자에게 문의해 주세요.",
  expired: "Gmail 연결 요청이 만료되었습니다. 다시 연결해 주세요.",
  config_missing: "서버의 Google 연결 설정이 끝나지 않았습니다. 관리자에게 문의해 주세요.",
  login_failed: "Gmail 연결을 완료하지 못했습니다. 다시 시도해 주세요.",
}

const WATCH_MESSAGES = {
  active: "메일 감시 중",
  stopped: "메일 감시 중지 · 다시 연결해 감시를 시작하세요.",
  expired: "메일 감시 만료 · 상태를 다시 확인하거나 재연결해 주세요.",
  error: "메일 감시 오류 · 상태를 다시 확인하거나 재연결해 주세요.",
}

export default function IntegrationSettings({ callback }) {
  const { state, refreshMe, retry } = useAuth()
  const token = state.accessToken
  const [read, setRead] = useState({ phase: "loading", gmail: null })
  const [reload, setReload] = useState(0)
  const [pending, setPending] = useState("")
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(() => {
    if (!callback) return ""
    return Object.hasOwn(CALLBACK_MESSAGES, callback) ? CALLBACK_MESSAGES[callback] : CALLBACK_MESSAGES.login_failed
  })
  const [confirmDisconnect, setConfirmDisconnect] = useState(false)
  const operation = useRef(null)

  useEffect(() => {
    const controller = new AbortController()
    setRead({ phase: "loading", gmail: null })
    setError(null)
    refreshMe(token, controller.signal).then((me) => {
      if (!controller.signal.aborted) setRead({ phase: "ready", gmail: me.gmail })
    }).catch((failure) => {
      if (!controller.signal.aborted) {
        setRead({ phase: "error", gmail: null })
        setError(failure)
      }
    })
    return () => controller.abort()
  }, [token, refreshMe, reload])

  useEffect(() => {
    setPending("")
    setConfirmDisconnect(false)
    return () => {
      operation.current?.abort()
      operation.current = null
    }
  }, [token])

  async function act(action) {
    if (operation.current) return
    const controller = new AbortController()
    operation.current = controller
    setPending(action)
    setError(null)
    setNotice("")
    let navigating = false
    try {
      const result = await apiFetch(`/gmail/${action}`, { method: "POST", token, signal: controller.signal })
      if (controller.signal.aborted) return
      if (action === "connect") {
        if (typeof result?.authorization_url !== "string" || !result.authorization_url.startsWith("https://")) {
          throw new Error("Google 동의 화면 주소를 확인할 수 없습니다. 상태를 다시 확인한 뒤 시도해 주세요.")
        }
        window.location.assign(result.authorization_url)
        navigating = true
      } else {
        setConfirmDisconnect(false)
        // 해제 응답이 아니라 서버의 현재 상태를 다시 확인한다. 이 조회가 실패하면 연결 여부는 미확인이다.
        setRead({ phase: "loading", gmail: null })
        const me = await refreshMe(token, controller.signal)
        if (controller.signal.aborted) return
        setRead({ phase: "ready", gmail: me.gmail })
        setNotice("Gmail 연결을 해제했습니다.")
      }
    } catch (failure) {
      if (!controller.signal.aborted) {
        setError(failure)
        // 요청 결과가 유실됐을 수도 있으므로 이전 상태를 현재 성공으로 표시하지 않는다.
        setRead({ phase: "error", gmail: null })
      }
    } finally {
      if (operation.current === controller && !navigating) {
        operation.current = null
        if (!controller.signal.aborted) setPending("")
      }
    }
  }

  const busy = Boolean(pending) || read.phase === "loading"
  const gmail = read.gmail
  return (
    <div className="integration-settings">
      {notice && <p role="status" className="section-note">{notice}</p>}
      {error && <div className="settings-load-error" role="alert">
        <p>{error.status === 401 ? "로그인이 만료되었거나 유효하지 않습니다. 로그인 상태를 다시 확인해 주세요." : error.message}</p>
        {error.status === 401 && <button className="btn" type="button" onClick={retry}>로그인 다시 확인</button>}
      </div>}
      <div className="integration-grid">
        <section className="integration-card" aria-label="Gmail 연동" aria-busy={busy}>
          <h3>Gmail</h3>
          <p className="section-note">메일 수신과 승인한 답장 발송에 사용합니다. 앱 로그인과 별도로 권한 동의가 필요합니다.</p>
          <p role="status">{read.phase === "loading" ? "연결 상태 확인 중…" : !gmail ? "연결 상태 미확인" : gmail.connected ? "연결됨" : "연결 안 됨"}</p>
          {gmail?.connected && <p className="section-note">{Object.hasOwn(WATCH_MESSAGES, gmail.watch) ? WATCH_MESSAGES[gmail.watch] : "메일 감시 상태를 확인해 주세요."}</p>}
          <div className="integration-actions">
            <button className="btn blue" type="button" disabled={busy || !gmail || error?.status === 401}
              onClick={() => act("connect")}>{pending === "connect" ? "Google 동의 화면으로 이동 중…" : gmail?.connected ? "Gmail 다시 연결" : "Gmail 연결"}</button>
            {gmail?.connected && <button className="btn" type="button" disabled={busy}
              onClick={() => setConfirmDisconnect(true)}>Gmail 연결 해제</button>}
            <button className="btn" type="button" disabled={busy} onClick={() => setReload((value) => value + 1)}>상태 다시 확인</button>
          </div>
          {confirmDisconnect && <div className="integration-confirm" role="group" aria-label="Gmail 연결 해제 확인">
            <p>Gmail 감시를 중지하고 저장된 토큰을 삭제하며 Google 권한을 폐기합니다. 같은 Google 앱에 연결한 다른 서비스도 재연결이 필요할 수 있습니다.</p>
            <div className="integration-actions">
              <button className="btn" type="button" disabled={busy} onClick={() => act("disconnect")}>{pending === "disconnect" ? "해제 중…" : "해제 확인"}</button>
              <button className="btn" type="button" disabled={busy} onClick={() => setConfirmDisconnect(false)}>취소</button>
            </div>
          </div>}
        </section>
        <section className="integration-card" aria-label="Google 캘린더 연동">
          <h3>Google 캘린더</h3>
          <p className="section-note">일정 연동 기능을 준비하고 있습니다.</p>
          <p>준비 중</p>
          <button className="btn" type="button" disabled>Google 캘린더 연결 · 준비 중</button>
        </section>
      </div>
    </div>
  )
}
