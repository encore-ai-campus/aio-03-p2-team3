const PARTY_LABELS = { legal_name: "회사명", legal_name_en: "회사명 (영문)", company_name: "회사명 (국문)", address: "주소", contact: "담당자", phone: "전화", email: "이메일", business_no: "사업자번호", ceo_name: "대표자", registration_details: "등록 정보" }
const BANK_LABELS = { BENEFICIARY: "수취인", BANK_NAME: "은행", BRANCH: "지점", SWIFT: "SWIFT", ACCOUNT_NUMBER: "계좌번호", BANK_ADDRESS: "은행 주소" }

function Details({ title, values, labels }) {
  return <section className="snapshot-section"><h3>{title}</h3><dl>{Object.entries(labels).filter(([key]) => values?.[key]).map(([key,label]) =>
    <div key={key}><dt>{label}</dt><dd>{values[key]}</dd></div>)}</dl></section>
}

export default function DocumentSnapshot({ document }) {
  return <div className="document-snapshot">
    <div className="snapshot-total"><span>{document.document_number || document.doc_no || "문서번호 미입력"}</span><b>{document.currency || ""} {document.total ?? "합계 확인 필요"}</b></div>
    <div className="snapshot-parties"><Details title="발행 회사" values={document.issuer} labels={PARTY_LABELS} />
      <Details title="판매자" values={document.seller} labels={PARTY_LABELS} /><Details title="구매자" values={document.buyer} labels={PARTY_LABELS} /></div>
    <div className="table-scroll"><table className="document-table"><thead><tr><th>품목</th><th>유상/무상 수량</th><th>단가</th><th>할인율</th><th>금액</th></tr></thead><tbody>
      {(document.items ?? []).map((item,index) => <tr key={index}><td>{item.product_name || "미입력"}<small>{[item.product_code,item.capacity,item.is_sample ? "샘플" : null].filter(Boolean).join(" · ")}</small></td>
        <td>{item.paid_quantity ?? item.quantity ?? "—"} / {item.free_quantity ?? "—"} {item.unit || ""}</td>
        <td>{item.unit_price ?? "—"}</td><td>{item.discount_percent ?? "—"}%</td><td>{item.line_total ?? "—"}</td></tr>)}
    </tbody></table></div>
    <dl className="snapshot-terms">{[['incoterms','납품 조건'],['payment_terms','지급 조건'],['ship_to','배송지'],['bill_to','청구지'],['remarks','비고']].map(([key,label]) =>
      document[key] ? <div key={key}><dt>{label}</dt><dd>{document[key]}</dd></div> : null)}</dl>
    {document.bank && <Details title="지급 계좌" values={document.bank} labels={BANK_LABELS} />}
  </div>
}
