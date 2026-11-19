import { Link } from "react-router-dom"
import { fieldLabel } from "../trade/fieldLabel"

export default function TradeDraftResult({ data }) {
  return <section className="directory-result" aria-label="작성 중인 무역서류">
    {data.draft_documents.length === 0 && <p>작성 중인 문서가 없습니다.</p>}
    <ul className="directory-cards">
      {data.draft_documents.map(doc => <li className="directory-card" key={doc.document_id}>
        <div className="directory-price-heading">
          <div><h3>{doc.kind} · {doc.title}</h3><span>{doc.counterparty && `${doc.counterparty} · `}버전 {doc.revision}</span></div>
          <Link className="doc-link" to={doc.url.replace(/^\/app/, "")}>이어서 작성</Link>
        </div>
        {doc.missing_fields.length > 0 ? <p>빠진 입력 · {doc.missing_fields.map(fieldLabel).join(", ")}</p>
          : <p>{doc.status === "ready" ? "발급 검토 가능" : "입력값 확인 필요"}</p>}
        {doc.issues.map((issue, index) => <p key={index}>{typeof issue === "string" ? issue : issue.message}</p>)}
      </li>)}
    </ul>
    {data.next_cursor && <p>다음 문서 목록을 요청할 수 있습니다.</p>}
  </section>
}
