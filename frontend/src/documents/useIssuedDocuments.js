import { useCallback, useEffect, useState } from "react"
import { apiFetch } from "../api.js"

// 생성된 문서(본인 PI·PO·CI·PL) 목록 — 무역 도메인별 목록 API 4종을 프런트에서 조합한다.
// 도메인 간 aggregation 엔드포인트는 만들지 않는다(documents-v2 계획 §2).

export const TRADE_KINDS = ["pi", "po", "ci", "pl"]
export const KIND_LABEL = { pi: "PI", po: "PO", ci: "CI", pl: "PL" }
export const TRADE_STATUS = {
  needs_input: { label: "작성 중", cls: "wait" },
  ready: { label: "검토 대기", cls: "run" },
  sending: { label: "발송 중", cls: "run" },
  sent: { label: "발급 완료", cls: "ok" },
}

// 4종 응답을 문서함 표 한 줄로 정규화한다. 순수 함수(테스트 대상).
export function normalizeIssued(byKind) {
  return TRADE_KINDS.flatMap((kind) => (byKind[kind] ?? []).map((doc) => ({
    kind, kindLabel: KIND_LABEL[kind], id: doc.document_id,
    number: doc.document_number || doc.doc_no,
    counterparty: doc.counterparty || null,
    status: doc.status, currency: doc.currency || null, total: doc.total || null,
    createdAt: doc.created_at || null,
  }))).sort((a, b) => (b.createdAt ?? "").localeCompare(a.createdAt ?? ""))
}

// 이름 검색: 문서번호·거래처·종류에서 대소문자 구분 없이 찾는다.
export function searchIssued(rows, query) {
  const needle = query.trim().toLowerCase()
  if (!needle) return rows
  return rows.filter((row) =>
    [row.number, row.counterparty, row.kindLabel].some((value) => value?.toLowerCase().includes(needle)))
}

// 총액 표시: 숫자면 천 단위 구분, 아니면 원문 그대로. 통화는 회색 접두로 붙인다.
export function formatTotal(row) {
  if (!row.total) return null
  const numeric = Number(row.total)
  const amount = Number.isFinite(numeric) ? numeric.toLocaleString("en-US") : row.total
  return { amount, currency: row.currency }
}

export function useIssuedDocuments(token) {
  const [state, setState] = useState({ rows: [], loading: true, error: "" })
  const [reload, setReload] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setState((previous) => ({ ...previous, loading: true, error: "" }))
    Promise.all(TRADE_KINDS.map((kind) =>
      apiFetch(`/trade/${kind}`, { token, signal: controller.signal }).catch((error) => {
        if (error.name === "AbortError") throw error
        throw new Error(`${KIND_LABEL[kind]} 문서를 불러오지 못했습니다. ${error.message}`)
      }),
    )).then((responses) => {
      if (controller.signal.aborted) return
      const byKind = {}
      TRADE_KINDS.forEach((kind, index) => { byKind[kind] = responses[index] })
      setState({ rows: normalizeIssued(byKind), loading: false, error: "" })
    }).catch((error) => {
      if (error.name === "AbortError") return
      setState({ rows: [], loading: false, error: error.message })
    })
    return () => controller.abort()
  }, [token, reload])

  const retry = useCallback(() => setReload((value) => value + 1), [])
  return { ...state, retry }
}
