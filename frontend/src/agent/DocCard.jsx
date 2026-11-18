import { useState } from "react"
import { Link } from "react-router-dom"
import { downloadFile } from "../api"

/* 시안 docs/plans/agent-chat-ui — 문서 카드(발급 결과·승인 공용). 종류 색칩로 PI/PO/CI/PL/견적을 구분한다. */

const DOWN_ICON = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3v12" /><path d="M7 10l5 5 5-5" /><path d="M4 21h16" /></svg>
const LINK_ICON = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><path d="M15 3h6v6" /><path d="M10 14L21 3" /></svg>
const ARROW_ICON = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14" /><path d="M13 6l6 6-6 6" /></svg>

export function FileButtons({ files, token, onError }) {
  return files?.map(file => <button type="button" className="file-btn" key={file.id} title={file.filename}
    aria-label={`${file.filename} 다운로드`} onClick={() => downloadFile(file, token).catch(error => onError(error.message))}>
    {DOWN_ICON}{(file.file_format || file.filename.split(".").pop() || "FILE").toUpperCase()}
  </button>)
}

function itemLine(item) {
  const quantity = [item.paid_quantity ?? item.quantity, item.free_quantity ? `/ ${item.free_quantity}` : null]
    .filter(Boolean).join(" ")
  return [quantity && `${quantity} ${item.unit || "EA"}`, item.unit_price != null && `단가 ${item.unit_price}`,
    item.discount_percent ? `할인 ${item.discount_percent}%` : null,
    item.line_total != null && item.line_total].filter(Boolean).join(" · ")
}

function FullItems({ items }) {
  const [open, setOpen] = useState(false)
  return <>
    <button type="button" className="btn doc-full-toggle" aria-expanded={open} onClick={() => setOpen(value => !value)}>
      {open ? "전체 품목 접기" : "전체 품목 표 보기"}
    </button>
    {open && <div className="doc-full"><dl className="kv">
      {items.map((item, index) => <div className="kv-row" key={index}>
        <dt>{item.product_name || item.product_code || `품목 ${index + 1}`}</dt>
        <dd>{itemLine(item) || "—"}</dd>
      </div>)}
    </dl></div>}
  </>
}

export default function DocCard({ chip, chipClass, number, meta, parties, itemsNote, items, total, link, files, token, onError, hero }) {
  return <article className={`doc-card${hero ? " hero" : ""}`}>
    <div className="doc-head">
      <span className={`kind-chip${chipClass ? ` ${chipClass}` : ""}`}>{chip}</span>
      {number && <span className="doc-number">{number}</span>}
      {link && <Link className="doc-link" to={link}>{LINK_ICON}문서 열기</Link>}
    </div>
    {parties && <div className="doc-parties"><b>{parties.from}</b>{ARROW_ICON}<b>{parties.to}</b></div>}
    {itemsNote && <p className="doc-items-note">{itemsNote}</p>}
    {meta && <p className="doc-meta">{meta}</p>}
    {(total || files?.length) && <div className="doc-foot">
      {total && <span className="doc-total">{total}</span>}
      {files?.length > 0 && <span className="doc-files"><FileButtons files={files} token={token} onError={onError} /></span>}
    </div>}
    {hero && items?.length > 0 && <FullItems items={items} />}
  </article>
}
