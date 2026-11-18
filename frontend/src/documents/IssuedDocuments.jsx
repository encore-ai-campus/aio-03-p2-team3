import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { TRADE_STATUS, formatTotal, searchIssued, useIssuedDocuments } from "./useIssuedDocuments"

// 생성된 문서 탭 — 본인 PI·PO·CI·PL의 메타데이터 표. 행을 누르면 기존 문서 화면으로 간다.
export default function IssuedDocuments({ token }) {
  const navigate = useNavigate()
  const { rows, loading, error, retry } = useIssuedDocuments(token)
  const [query, setQuery] = useState("")
  // 검색·필터는 파생값이라 렌더 중에 계산한다(상태로 두지 않는다).
  const visible = searchIssued(rows, query)

  return <section aria-label="생성된 문서 목록">
    <div className="doc-toolbar">
      <div className="doc-search">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg>
        <input type="search" value={query} onChange={(event) => setQuery(event.target.value)}
          placeholder="문서번호·거래처 검색" aria-label="문서번호·거래처 검색" />
      </div>
      <span className="doc-total">{loading ? "" : `${visible.length}건`}</span>
    </div>

    <div className="doc-list">
      <div className="doc-row doc-row-head" aria-hidden="true">
        <span>종류</span><span>문서번호 · 거래처</span><span>상태</span><span className="num">총액</span><span>등록일</span>
      </div>
      {error && <div className="doc-block-error" role="alert">
        <p>{error}</p>
        <button type="button" className="doc-retry" onClick={retry}>다시 시도</button>
      </div>}
      {loading && [1, 2, 3, 4].map((line) => <div key={line} className="doc-row doc-loading" aria-hidden="true"><span /></div>)}
      {!loading && !error && !visible.length && (
        <div className="doc-block-empty">
          <p>{rows.length ? "검색에 맞는 문서가 없습니다." : "생성된 문서가 없습니다."}</p>
          {!rows.length && <p className="doc-hint">문서작성에서 PI·PO·CI·PL을 만들면 여기에 표시됩니다.</p>}
        </div>
      )}
      {visible.map((row, index) => {
        const status = TRADE_STATUS[row.status]
        const total = formatTotal(row)
        return <button key={`${row.kind}-${row.id}`} type="button" className="doc-row"
          style={{ animationDelay: `${Math.min(index, 8) * 40}ms` }}
          onClick={() => navigate(`/trade/${row.kind}/${row.id}`)}>
          <span className={"doc-kind k-" + row.kind}>{row.kindLabel}</span>
          <span className="doc-id">
            <span className="doc-number">{row.number}</span>
            <span className="doc-party">{row.counterparty ?? "—"}</span>
          </span>
          <span className={"doc-pill p-" + (status?.cls ?? "off")}><i />{status?.label ?? row.status}</span>
          <span className="doc-total-cell num">{total
            ? <>{total.amount}{total.currency && <small> {total.currency}</small>}</>
            : "—"}</span>
          <span className="doc-date num">{row.createdAt ? row.createdAt.slice(0, 10) : "—"}</span>
        </button>
      })}
    </div>
  </section>
}
