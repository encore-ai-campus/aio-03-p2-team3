import PrivateImage from "../components/PrivateImage"
import DocumentSnapshot from "./DocumentSnapshot"

export default function ReviewPanel({ proposal, token, kind = "pi", busy, dirty, modifying, onDecision, onModify, onDownload, headingRef }) {
  const payload = proposal.payload
  const statuses = { pending: "승인 대기", approved: "발급 완료", cancelled: "검토 취소", superseded: "새 검토 필요" }
  const base = `/trade/${kind}/${proposal.document_id}/reviews/${proposal.id}/branding`
  return <section className="card review-panel" aria-label="최종 검토 제안">
    <div className="panel-head"><h2 className="section-title" tabIndex={-1} ref={headingRef}>최종 검토 · 버전 {proposal.revision}</h2><span className="document-status">{statuses[proposal.status] ?? proposal.status}</span></div>
    <p className="section-note">아래 문서·회사·계좌·이미지를 고정한 검토입니다. 승인하면 파일을 발급하며 메일은 발송하지 않습니다.</p>
    {dirty && <p className="form-error">입력한 변경사항을 먼저 저장하고 다시 검토해 주세요.</p>}
    {modifying && <p className="form-success">위 입력을 수정한 뒤 ‘수정 저장·재검토’를 눌러 주세요.</p>}
    <DocumentSnapshot document={payload.document} />
    <div className="review-branding"><div><h3>직인</h3><PrivateImage path={`${base}/seal`} token={token} label="직인" /></div>
      {payload.logo_sha256 && <div><h3>로고</h3><PrivateImage path={`${base}/logo`} token={token} label="로고" /></div>}</div>
    <details className="review-proof"><summary>고정된 버전·파일 정보</summary><dl>
      <div><dt>검토 내용 해시</dt><dd>{proposal.content_hash}</dd></div><div><dt>직인 해시</dt><dd>{payload.seal_sha256}</dd></div>
      {payload.logo_sha256 && <div><dt>로고 해시</dt><dd>{payload.logo_sha256}</dd></div>}
      <div><dt>발급 형식</dt><dd>{payload.formats.map((format) => format.toUpperCase()).join(" · ")}</dd></div>
    </dl></details>
    {proposal.status === "pending" && <div className="form-actions">
      <button className="btn" type="button" disabled={busy || modifying} onClick={() => onDecision("cancel")}>검토 취소</button>
      <button className="btn" type="button" disabled={busy || modifying} onClick={onModify}>수정</button>
      <button className="btn blue" type="button" disabled={busy || dirty || modifying} onClick={() => onDecision("approve")}>승인하고 파일 발급</button>
    </div>}
    {proposal.status === "approved" && <div className="form-actions">{proposal.files.map((file) =>
      <button className="btn blue" key={file.id} type="button" disabled={busy} onClick={() => onDownload(file)}>{file.file_format.toUpperCase()} 다운로드</button>)}</div>}
  </section>
}
