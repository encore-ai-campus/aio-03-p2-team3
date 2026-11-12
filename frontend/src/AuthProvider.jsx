import { useEffect, useState } from "react"
import { AuthContext } from "./AuthContext"
import { fetchMe } from "./api"
import { supabase } from "./supabase"

// 인증 컨텍스트: Supabase 세션 하나를 앱 전체가 공유한다.
// phase: "loading"(확인 중) → "authenticated"(/api/me 확인됨) · "signed-out" · "error"(서버 장애) · "unconfigured"(설정 누락)
// 조회는 Auth 구독 이벤트에서 1회만 요청하고(Effect로 반복 조회하지 않는다) 구독은 cleanup으로 해제한다.

async function applySession(session, setState) {
  if (!session) {
    setState((prev) => ({ ...prev, phase: "signed-out", me: null }))
    return
  }
  try {
    const me = await fetchMe(session.access_token)
    setState({ phase: "authenticated", me, notice: "" })
  } catch (error) {
    if (error.status === 401) {
      // 서버가 토큰을 거부했다(만료·변조). 로컬 세션을 정리하고 로그인 복구를 안내한다.
      await supabase.auth.signOut()
      setState({ phase: "signed-out", me: null, notice: "로그인이 만료되었거나 유효하지 않습니다. 다시 로그인해 주세요." })
    } else {
      setState((prev) => ({ ...prev, phase: "error", notice: error.message }))
    }
  }
}

export function AuthProvider({ children }) {
  const [state, setState] = useState({
    phase: supabase ? "loading" : "unconfigured",
    me: null,
    notice: "",
  })

  useEffect(() => {
    if (!supabase) return undefined
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      if (session && (event === "SIGNED_IN" || event === "INITIAL_SESSION" || event === "TOKEN_REFRESHED")) {
        applySession(session, setState)
      } else if (!session && (event === "SIGNED_OUT" || event === "INITIAL_SESSION")) {
        // notice는 만료·오류 안내를 지우지 않는다(직접 로그아웃할 때만 지운다).
        setState((prev) => ({ ...prev, phase: "signed-out", me: null }))
      }
    })
    return () => subscription.unsubscribe()
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
    setState((prev) => ({ ...prev, notice: "" }))
    await supabase.auth.signOut()
  }

  async function retry() {
    setState((prev) => ({ ...prev, phase: "loading" }))
    const { data: { session } } = await supabase.auth.getSession()
    await applySession(session, setState)
  }

  return (
    <AuthContext.Provider value={{ state, signInWithGoogle, signOut, retry }}>
      {children}
    </AuthContext.Provider>
  )
}
