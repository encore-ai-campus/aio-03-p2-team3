// 아직 API에 연결되지 않은 화면의 자리: 시안의 제목·설명 문구만 두고 가짜 성공 처리를 하지 않는다.
export default function PlaceholderPage({ title, sub }) {
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{title}</h1>
          <p className="page-sub">{sub}</p>
        </div>
      </div>
      <div className="card">
        <div className="panel-head">
          <div>
            <h2 className="section-title">화면 준비 중</h2>
            <div className="section-note">이 화면은 아직 서버 API에 연결되지 않았습니다.</div>
          </div>
        </div>
        <p className="section-note">연결되면 실제 데이터로 채워집니다.</p>
      </div>
    </>
  )
}
