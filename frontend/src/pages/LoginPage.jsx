import { useState } from "react"
import { Navigate } from "react-router-dom"
import { useAuth } from "../useAuth"
import { supabase } from "../supabase"

// Google 로그인을 마치지 않고 돌아온 경우(취소·거부) URL에 오류 표시가 남는다.
function readReturnError() {
  const query = new URLSearchParams(window.location.search)
  const hash = new URLSearchParams(window.location.hash.slice(1))
  return Boolean(
    query.get("error") || query.get("error_description") ||
    hash.get("error") || hash.get("error_description"),
  )
}

export default function LoginPage() {
  const { state, signInWithGoogle } = useAuth()
  const [pending, setPending] = useState(false)
  const [returnedWithoutLogin] = useState(readReturnError)

  if (state.phase === "authenticated") return <Navigate to="/" replace />

  // 상태별 안내: 설정 누락 → 취소 반환 → 만료/오류(state.notice) 순서로 보여 준다.
  const notice = !supabase
    ? "Supabase 설정이 없습니다. frontend/.env에 VITE_SUPABASE_URL·VITE_SUPABASE_PUBLISHABLE_KEY를 설정해 주세요."
    : returnedWithoutLogin
      ? "Google 로그인이 완료되지 않았습니다. 다시 시도해 주세요."
      : state.notice

  async function handleGoogleLogin() {
    setPending(true)
    await signInWithGoogle()
    // 정상이면 Google 로그인 페이지로 이동하므로 아래 줄은 시작 실패 때만 실행된다.
    setPending(false)
  }

  return (
    <main className="login">
      <section className="login-art">
        <div className="logo"><span className="logo-mark">↗</span> TradeMate</div>
        <div className="login-copy">
          <div className="eyebrow">TRADE DOCUMENT WORKSPACE</div>
          <h1>업무는 한눈에,<br />문서는 정확하게.</h1>
          <p>메일 승인부터 견적서와 무역 문서 관리까지, 필요한 업무를 한곳에서 확인하세요.</p>
        </div>
        <div className="login-foot">TradeMate · 안전한 무역 문서 작업 공간</div>
      </section>
      <section className="login-panel">
        <div className="login-form">
          <div className="eyebrow">WELCOME BACK</div>
          <h2>로그인</h2>
          <p>Google 계정으로 로그인해 업무를 이어가세요.</p>
          <button className="google" disabled={!supabase || pending} onClick={handleGoogleLogin} type="button">
            <b>G</b> {pending ? "Google 로그인 페이지로 이동합니다…" : "Google 계정으로 계속하기"}
          </button>
          {notice ? <p aria-live="polite" className="login-tip" role="status">{notice}</p> : null}
          <p className="fine">
            로그아웃해도 브라우저에 남은 유효한 로그인 토큰은 만료까지 사용될 수 있습니다.
          </p>
        </div>
      </section>
    </main>
  )
}
