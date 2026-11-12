import { Link } from "react-router-dom"
import { useAuth } from "../useAuth"

// 연결한 문서만 작성 링크를 제공한다. 뒤 문서는 각 계획 절에서 순서대로 연결한다.
// 시안의 작업현황 수치·최근 문서·성공 표시는 실제 집계 API가 연결될 때까지 두지 않는다(계획 17절).
export default function DashboardPage() {
  const { state } = useAuth()
  const me = state.me

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">문서작성</h1>
          <p className="page-sub">문서 종류를 선택하고 거래 내용을 입력해 검토·발급하세요.</p>
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
              <h2 className="section-title">새 문서 만들기</h2>
              <div className="section-note">PI 작성 화면을 이용할 수 있습니다.</div>
            </div>
          </div>
          <Link className="btn blue" to="/trade/pi">PI 작성하기</Link>
          <p className="section-note">PO·CI·PL은 후속 단계에서 연결합니다.</p>
        </div>
      </div>
    </>
  )
}
