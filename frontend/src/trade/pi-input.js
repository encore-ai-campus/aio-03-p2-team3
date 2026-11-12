export function emptyPI() {
  return { product_family: "other", document_number: "", currency: "USD", buyer: {}, seller: {},
    incoterms: "", payment_terms: "", remarks: "", ship_to: "", bill_to: "", items: [newPIItem()] }
}

export function newPIItem(values = {}) {
  return { rowId: crypto.randomUUID(), product_name: "", capacity: "", quantity: "", unit: "PCS",
    discount_percent: "0", is_sample: false, confirm_price_override: false, ...values }
}

export function piDraft(input) {
  return { ...emptyPI(), ...input, items: (input.items ?? []).map((item) => newPIItem(item)) }
}

export function piPayload(draft) {
  return { ...draft, currency: draft.currency || null,
    items: draft.items.map((row) => {
      const item = { ...row }
      delete item.rowId
      return item
    }) }
}

