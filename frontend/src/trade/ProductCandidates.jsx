import { useEffect, useState } from "react"
import { apiFetch } from "../api"

export default function ProductCandidates({ name, role, token, index, onSelect }) {
  const query = String(name ?? "").trim()
  const [result, setResult] = useState(null)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    if (query.length < 2 || query.length > 200) return
    const controller = new AbortController()
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ q: query, ...(role ? { role } : {}) })
      apiFetch(`/trade/settings/products/search?${params}`, { token, signal: controller.signal })
        .then((data) => {
          if (!controller.signal.aborted) setResult({ query, role, data, retry })
        }).catch((error) => {
          if (!controller.signal.aborted) setResult({ query, role, error: error.message, retry })
        })
    }, 250)
    return () => { clearTimeout(timer); controller.abort() }
  }, [query, role, token, retry])
  if (query.length < 2) return null
  if (query.length > 200) return <p className="section-note">후보 검색은 품목명을 200자 이내로 입력해 주세요.</p>
  const current = result?.query === query && result?.role === role && result?.retry === retry ? result : null
  if (!current) return <p role="status">비슷한 등록 품목을 찾고 있어요…</p>
  if (current.error) return <div role="status">{current.error} 입력은 유지됩니다.
    <button type="button" className="btn" aria-label={`품목 ${index+1} 후보 다시 찾기`} onClick={() => setRetry((value) => value + 1)}>품목 후보 다시 찾기</button></div>
  const { candidates, total } = current.data
  if (total === 1 && candidates[0].product.item_name === query) return null
  return <section className="product-candidates" aria-label={`품목 ${index+1} 후보`}>
    <p role="status">{total ? `비슷한 등록 품목 ${total}개를 찾았습니다. 사용할 품목을 선택해 주세요.`
      : "비슷한 등록 품목이 없습니다. 검색어를 바꾸거나 품목명을 직접 수정해 계속 작성하세요."}</p>
    {total > 20 && <p>상위 20개를 표시합니다. 색상·모델명을 추가하면 후보를 좁힐 수 있어요.</p>}
    <ul>{candidates.map(({ product }) => <li key={product.id}>
      <button type="button" className="btn" onClick={() => onSelect(product)}>
        {product.item_name}{[product.source_code, product.capacity].filter(Boolean).length > 0 &&
          <small> · {[product.source_code, product.capacity].filter(Boolean).join(" · ")}</small>} 선택
      </button>
    </li>)}</ul>
  </section>
}
