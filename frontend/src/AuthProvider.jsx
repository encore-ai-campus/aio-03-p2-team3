import { useEffect, useRef, useState } from "react"
import { AuthContext } from "./AuthContext"
import { apiFetch, fetchMe } from "./api"
import { supabase } from "./supabase"

// 인증 컨텍스트: Supabase 세션 하나를 앱 전체가 공유한다.
// phase: "loading"(확인 중) → "authenticated"(/api/me 확인됨) · "signed-out" · "error"(서버 장애) · "unconfigured"(설정 누락)
// 조회는 Auth 구독 이벤트에서 1회만 요청하고(Effect로 반복 조회하지 않는다) 구독은 cleanup으로 해제한다.

async function applySession(session, setState, signal) {
  if (signal.aborted) return
  if (!session) {
    setState((prev) => ({ ...prev, phase: "signed-out", me: null, accessToken: null }))
    return
  }
  try {
    const me = await fetchMe(session.access_token, signal)
    if (!signal.aborted) setState({ phase: "authenticated", me, accessToken: session.access_token, notice: "" })
  } catch (error) {
    if (signal.aborted) return
    if (error.status === 401) {
      // 서버가 토큰을 거부했다(만료·변조). 로컬 세션을 정리하고 로그인 복구를 안내한다.
      setState({ phase: "signed-out", me: null, accessToken: null, notice: "로그인이 만료되었거나 유효하지 않습니다. 다시 로그인해 주세요." })
      await supabase.auth.signOut({ scope: "local" })
    } else {
      setState((prev) => ({ ...prev, phase: "error", notice: error.message }))
    }
  }
}

export function AuthProvider({ children }) {
  const currentRequest = useRef(null)
  const [state, setState] = useState({
    phase: supabase ? "loading" : "unconfigured",
    me: null,
    accessToken: null,
    notice: "",
  })

  useEffect(() => {
    if (!supabase) return undefined
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      currentRequest.current?.abort()
      const controller = new AbortController()
      currentRequest.current = controller
      if (session && (event === "SIGNED_IN" || event === "INITIAL_SESSION" || event === "TOKEN_REFRESHED")) {
        applySession(session, setState, controller.signal)
      } else if (!session && (event === "SIGNED_OUT" || event === "INITIAL_SESSION")) {
        // notice는 만료·오류 안내를 지우지 않는다(직접 로그아웃할 때만 지운다).
        setState((prev) => ({ ...prev, phase: "signed-out", me: null, accessToken: null }))
      }
    })
    return () => {
      currentRequest.current?.abort()
      subscription.unsubscribe()
    }
  }, [])

  async function signInWithGoogle() {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/app/login` },
    })
    if (error) {
      setState((prev) => ({ ...prev, notice: `Google 로그인을 시작하지 못했습니다. ${error.message}` }))
    }
  }

  async function signOut() {
    try {
      const { data: { session } } = await supabase.auth.getSession()
      if (session) await apiFetch("/gmail/logout", { method: "POST", token: session.access_token })
      currentRequest.current?.abort()
      const { error } = await supabase.auth.signOut()
      if (error) throw error
      setState({ phase: "signed-out", me: null, accessToken: null, notice: "" })
    } catch (error) {
      setState((prev) => ({ ...prev, notice: `로그아웃을 완료하지 못했습니다. ${error.message}` }))
    }
  }

  async function retry() {
    currentRequest.current?.abort()
    const controller = new AbortController()
    currentRequest.current = controller
    setState((prev) => ({ ...prev, phase: "loading" }))
    const { data: { session } } = await supabase.auth.getSession()
    await applySession(session, setState, controller.signal)
  }

  return (
    <AuthContext.Provider value={{ state, signInWithGoogle, signOut, retry }}>
      {children}
    </AuthContext.Provider>
  )
}
