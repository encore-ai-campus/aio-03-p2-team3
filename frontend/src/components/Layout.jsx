import { NavLink, Outlet, useLocation } from "react-router-dom"
import { useAuth } from "../useAuth"

// 시안의 사이드바(WORKSPACE·MANAGE)·상단바·모바일 헤더·하단탐색. 활성 표시는 NavLink가 담당한다.
const WORKSPACE_NAV = [
  { to: "/", label: "문서작성", icon: "✦", end: true },
  { to: "/status", label: "작업현황", icon: "▦" },
  { to: "/inbox", label: "받은 메일", icon: "✉" },
  { to: "/documents", label: "문서함", icon: "▤" },
  { to: "/activity", label: "실행 기록", icon: "◷" },
]
const MANAGE_NAV = [{ to: "/settings", label: "설정", icon: "⚙" }]
const BOTTOM_NAV = [
  { to: "/", label: "문서작성", icon: "✦", end: true },
  { to: "/status", label: "작업현황", icon: "▦" },
  { to: "/inbox", label: "업무함", icon: "✉" },
  { to: "/documents", label: "문서", icon: "▤" },
  { to: "/settings", label: "설정", icon: "⚙" },
]
const PAGE_LABELS = {
  "/": "문서작성",
  "/status": "작업현황",
  "/inbox": "받은 메일",
  "/documents": "문서함",
  "/activity": "실행 기록",
  "/settings": "설정",
}

function navClass({ isActive }) {
  return isActive ? "nav active" : "nav"
}

export default function Layout() {
  const { state, signOut } = useAuth()
  const { pathname } = useLocation()
  // 사이드바 계정 정보는 /api/me 응답(실제 로그인 사용자)으로 채운다.
  const me = state.me
  const displayName = me?.display_name || me?.email || "사용자"

  return (
    <div className="shell">
      <aside className="side">
        <div className="logo"><span className="logo-mark">↗</span> TradeMate</div>
        <div className="nav-label">WORKSPACE</div>
        {WORKSPACE_NAV.map((item) => (
          <NavLink key={item.to} className={navClass} end={item.end} to={item.to}>
            <i>{item.icon}</i>{item.label}
          </NavLink>
        ))}
        <div className="nav-label">MANAGE</div>
        {MANAGE_NAV.map((item) => (
          <NavLink key={item.to} className={navClass} to={item.to}>
            <i>{item.icon}</i>{item.label}
          </NavLink>
        ))}
        <div className="side-user">
          <span className="avatar">{displayName.slice(0, 1)}</span>
          <span>{displayName}<br /><span style={{ color: "#99a1ac" }}>{me?.email ?? ""}</span></span>
        </div>
      </aside>
      <main className="shell-main">
        <header className="top">
          <div className="crumb">워크스페이스 / {PAGE_LABELS[pathname] ?? ""}</div>
          <div className="top-actions">
            <button className="link-button" type="button" onClick={signOut}>로그아웃</button>
          </div>
        </header>
        <header className="mobile-head">
          <div className="logo"><span className="logo-mark">↗</span> TradeMate</div>
          <button className="link-button" type="button" onClick={signOut}>로그아웃</button>
        </header>
        <div className="content">
          {state.notice && <p role="alert">{state.notice}</p>}
          <Outlet />
        </div>
      </main>
      <nav className="bottom-nav">
        {BOTTOM_NAV.map((item) => (
          <NavLink key={item.to} end={item.end} to={item.to}>
            <b>{item.icon}</b>{item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
