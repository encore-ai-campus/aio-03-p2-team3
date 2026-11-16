import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom"
import { AuthProvider } from "./AuthProvider"
import { useAuth } from "./useAuth"
import Layout from "./components/Layout"
import DashboardPage from "./pages/DashboardPage"
import LoginPage from "./pages/LoginPage"
import PlaceholderPage from "./pages/PlaceholderPage"
import SettingsPage from "./pages/SettingsPage"
import PIPage from "./pages/PIPage"
import KnowledgePage from "./knowledge/KnowledgePage"
import POPage from "./pages/POPage"
import CIPage from "./pages/CIPage"
import CIStandalonePage from "./pages/CIStandalonePage"
import PLPage from "./pages/PLPage"

// 인증 경계: /app 아래는 /api/me까지 확인된 로그인만 지난다.
function RequireAuth() {
  const { state, retry } = useAuth()
  if (state.phase === "authenticated") return <Outlet />
  if (state.phase === "loading") {
    return <div className="boot">로그인 상태를 확인하는 중입니다…</div>
  }
  if (state.phase === "error") {
    return (
      <div className="boot">
        <p role="status">{state.notice}</p>
        <button className="btn" type="button" onClick={retry}>다시 시도</button>
      </div>
    )
  }
  // signed-out(로그인 필요·만료)·unconfigured(설정 누락 안내는 로그인 화면이 보여 준다)
  return <Navigate to="/login" replace />
}

function LegacyKnowledgeRedirect() {
  const { search, hash } = useLocation()
  return <Navigate to={{ pathname: "/documents", search, hash }} replace />
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter basename="/app">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RequireAuth />}>
            <Route element={<Layout />}>
              <Route index element={<DashboardPage />} />
              <Route path="status" element={<PlaceholderPage sub="오늘 확인할 업무와 최근 문서를 모았어요." title="작업현황" />} />
              <Route path="inbox" element={<PlaceholderPage sub="답장 내용을 확인하고 보낼 후보를 선택하세요." title="받은 메일" />} />
              <Route path="documents" element={<KnowledgePage />} />
              <Route path="activity" element={<PlaceholderPage sub="처리 단계와 오류를 확인하는 작업 이력입니다." title="실행 기록" />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="knowledge" element={<LegacyKnowledgeRedirect />} />
              <Route path="trade/pi" element={<PIPage />} />
              <Route path="trade/pi/:documentId" element={<PIPage />} />
              <Route path="trade/po" element={<POPage />} />
              <Route path="trade/po/:documentId" element={<POPage />} />
              <Route path="trade/ci" element={<CIPage />} />
              <Route path="trade/ci/standalone" element={<CIStandalonePage />} />
              <Route path="trade/ci/standalone/:documentId" element={<CIStandalonePage />} />
              <Route path="trade/ci/:documentId" element={<CIPage />} />
              <Route path="trade/pl" element={<PLPage />} />
              <Route path="trade/pl/:documentId" element={<PLPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
