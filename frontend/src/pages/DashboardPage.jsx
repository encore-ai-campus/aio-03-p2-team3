import { Link } from "react-router-dom"
import { useAuth } from "../useAuth"

// 대시보드 뼈대: 시안 문서작성 화면의 제목 갈래를 살리고, 본문 자리는 아직 연결 전임을 보여 준다.
// 시안의 작업현황 수치·최근 문서·성공 표시는 실제 집계 API가 연결될 때까지 두지 않는다(계획 17절).
export default function DashboardPage() {
  const { state } = useAuth()
  const me = state.me

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">문서작성</h1>
          <p className="page-sub">대화로 조건을 전달하고 문서 요약과 검토 결과를 함께 확인하세요.</p>
        </div>
        <Link className="btn" to="/documents">문서함으로</Link>
      </div>
      <div className="grid">
        <div className="card">
          <div className="panel-head">
            <div>
              <h2 className="section-title">내 계정</h2>
              <div className="section-note">로그인한 계정 정보(/api/me)</div>
            </div>
          </div>
          <div className="summary-row"><span>표시 이름</span><b>{me?.display_name || "-"}</b></div>
          <div className="summary-row"><span>이메일</span><b>{me?.email || "-"}</b></div>
          <div className="summary-row"><span>사용자 ID</span><b>{me?.user_id ?? "-"}</b></div>
          <div className="summary-row"><span>Gmail 연결</span><b>{me?.gmail?.connected ? "연결됨" : "미연결"}</b></div>
          <div className="summary-row"><span>Gmail 감시</span><b>{me?.gmail?.watch ?? "-"}</b></div>
        </div>
        <div className="card">
          <div className="panel-head">
            <div>
              <h2 className="section-title">문서작성 화면 준비 중</h2>
              <div className="section-note">PI·PO·CI·PL 작성 화면은 순서대로 연결됩니다.</div>
            </div>
          </div>
          <p className="section-note">이 자리에 문서작성 대화 화면이 연결됩니다. 아직 실제 데이터를 보여 주지 않습니다.</p>
        </div>
      </div>
    </>
  )
}
