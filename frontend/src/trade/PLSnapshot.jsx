const PARTY = [["legal_name","회사명"],["legal_name_en","회사명 (영문)"],["company_name","회사명 (국문)"],["address","주소"],["contact","담당자"],["phone","전화"],["email","이메일"],["registration_details","등록 정보"]]

export default function PLSnapshot({ document }) {
  const totals = document.packing_totals
  return <div className="document-snapshot"><div className="snapshot-total"><span>{document.document_number || document.doc_no || "문서번호 미입력"}</span><b>{totals?.approved ? "포장 합계 승인 완료" : "포장 합계 확인 필요"}</b></div>
    <div className="snapshot-parties">{[["issuer","발행 회사"],["seller","판매자"],["buyer","구매자"]].map(([role,label]) => <section className="snapshot-section" key={role}><h3>{label}</h3><dl>{PARTY.filter(([key]) => document[role]?.[key]).map(([key,title]) => <div key={key}><dt>{title}</dt><dd>{document[role][key]}</dd></div>)}</dl></section>)}</div>
    <p className="section-note">품목·별도 포장 표는 좌우로 스크롤할 수 있어요. 키보드는 표에 초점을 둔 뒤 방향키로 이동해 주세요.</p>
    <div className="table-scroll" role="region" aria-label="PL 품목·포장 · 가로 스크롤" tabIndex={0}><table className="document-table"><thead><tr>{["품목","수량","포장 수·종류","순중량 kg","총중량 kg","부피 CBM"].map((label) => <th key={label} scope="col">{label}</th>)}</tr></thead><tbody>{(document.items ?? []).map((row,index) =>
      <tr key={index}><td>{row.product_name}<small>{[row.product_code,row.capacity].filter(Boolean).join(" · ")}</small>
        {row.dimensions && <small>치수: {row.dimensions}</small>}{row.shipping_marks && <small>배송 표시: {row.shipping_marks}</small>}
        {row.source && <small>출처: {row.source}</small>}</td><td>{row.quantity} {row.unit}</td><td>{row.package_count ?? "—"} {row.package_type}</td><td>{row.net_weight_kg ?? "—"}</td><td>{row.gross_weight_kg ?? "—"}</td><td>{row.volume_cbm ?? "—"}</td></tr>)}</tbody></table></div>
    {document.packages?.length > 0 && <div className="table-scroll" role="region" aria-label="PL 별도 포장 행 · 가로 스크롤" tabIndex={0}><table className="document-table"><caption>별도 포장 행</caption><thead><tr>{["포장 종류","포장 수","순중량 kg","총중량 kg","치수","배송 표시"].map((label) => <th key={label} scope="col">{label}</th>)}</tr></thead><tbody>{document.packages.map((row,index) => <tr key={index}>{["package_type","package_count","net_weight_kg","gross_weight_kg","dimensions","shipping_marks"].map((key) => <td key={key}>{row[key] ?? "—"}</td>)}</tr>)}</tbody></table></div>}
    <dl className="packing-quantities">{Object.entries(totals?.quantities ?? {}).map(([unit,value]) => <div key={unit}><dt>{unit}</dt><dd>{value}</dd></div>)}</dl>
    <dl className="snapshot-terms">{[["shipment_reference","선적 참조"],["hs_code","HS 코드"],["incoterms","납품 조건"],["actual_package_count","포장 수"],["container_count","컨테이너"],["declared_net_weight_kg","순중량 kg"],["declared_gross_weight_kg","총중량 kg"],["declared_volume_cbm","부피 CBM"],["ship_to","배송지"],["bill_to","청구지"],["remarks","비고"]].filter(([key]) => document[key] != null && document[key] !== "").map(([key,label]) => <div key={key}><dt>{label}</dt><dd>{document[key]}</dd></div>)}</dl>
  </div>
}
