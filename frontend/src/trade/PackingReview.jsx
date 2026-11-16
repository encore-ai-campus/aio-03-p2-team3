import { canApprovePacking, PACKING_TOTAL_FIELDS } from "./pl-input"

export default function PackingReview({ view, current, dirty, disabled, onReload, onDecision, onEdit }) {
  const document = view?.payload.document
  const totals = document?.packing_totals
  const original = document?._packing_original_totals ?? document
  const matched = view && current && view.document_id === current.document_id && view.revision === current.revision
  return <section aria-label="포장 합계 확인"><h3 className="section-title">원본과 계산 합계 확인</h3>
    <p className="section-note">합계 승인은 파일 발급 승인과 별개입니다. 원본과 다른 값은 확인 후 계산 가능한 항목만 적용합니다.</p>
    {dirty && <p className="form-error" role="alert">미저장 변경사항을 먼저 저장하고 합계를 다시 확인해 주세요.</p>}
    {!matched && <p className="section-note">현재 버전의 포장 합계를 읽어 주세요.</p>}
    {matched && totals && <>
      <div className="table-scroll"><table className="document-table"><caption className="sr-only">원본과 서버 계산 합계</caption><thead><tr><th>항목</th><th>원본 합계</th><th>서버 계산 합계</th></tr></thead>
        <tbody>{PACKING_TOTAL_FIELDS.map(([field,label,key]) => <tr key={field}><td>{label}</td><td>{original?.[field] ?? "미입력"}</td><td>{totals.calculated[key] ?? "계산 불가"}</td></tr>)}</tbody></table></div>
      <dl className="packing-quantities">{Object.entries(totals.quantities).map(([unit,value]) => <div key={unit}><dt>{unit}</dt><dd>{value}</dd></div>)}</dl>
      <p className="section-note">원본 총수량: {original?.declared_total_quantity ?? "미입력"} {original?.declared_total_quantity_unit}<br />원본 컨테이너: {original?.container_count || "없음"}</p>
      <p className="section-note">별도 포장 행 순중량: {totals.packages_total.net_weight_kg ?? "없음"} kg · 총중량: {totals.packages_total.gross_weight_kg ?? "없음"} kg</p>
      {totals.changes.length > 0 && <div className="pi-missing"><p>승인 시 반영할 변경</p><ul>{totals.changes.map((change) => <li key={change.field}>{PACKING_TOTAL_FIELDS.find(([key]) => key === change.field)?.[1] ?? change.label}: {change.source} → {change.calculated}</li>)}</ul></div>}
      {totals.discrepancies.length > 0 && <div className="pi-missing"><p>원본과 계산의 차이</p><ul>{totals.discrepancies.map((message,index) => <li key={index}>{message}</li>)}</ul></div>}
      {(totals.issues.length > 0 || !totals.quantity_complete) && <div className="form-error" role="alert"><p>포장 행과 수량·단위를 먼저 수정해 주세요.</p><ul>{totals.issues.map((message,index) => <li key={index}>{message}</li>)}</ul></div>}
      {totals.approved && <p className="form-success" role="status">포장 합계를 승인했습니다. 다른 누락 항목도 없으면 별도로 최종 검토를 만들 수 있습니다.</p>}
    </>}
    <div className="form-actions"><button className="btn" type="button" disabled={disabled} onClick={onEdit}>포장 행 수정</button>
      <button className="btn" type="button" disabled={disabled || dirty} onClick={onReload}>합계 다시 읽기</button>
      <button className="btn" type="button" disabled={disabled || dirty || !matched} onClick={() => onDecision("cancel")}>합계 취소</button>
      <button className="btn blue" type="button" disabled={disabled || !canApprovePacking(view,current,dirty)} onClick={() => onDecision("approve")}>합계 승인</button></div>
  </section>
}
