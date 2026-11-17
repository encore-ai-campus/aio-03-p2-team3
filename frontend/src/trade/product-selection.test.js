import assert from "node:assert/strict"
import test from "node:test"
import { selectProduct } from "./product-selection.js"

test("후보 선택은 해당 행의 SKU를 바꾸고 수량·입력단가·할인을 보존한다", () => {
  const row = { rowId: "stable-row", product_name: "슈퍼라이트", product_code: "old", capacity: "old",
    quantity: "25", unit_price: "139", discount_percent: "10", confirm_price_override: true }
  const result = selectProduct(row, { item_name: "PRO X SUPERLIGHT2 Black", source_code: null, capacity: null })
  assert.equal(result.product_name, "PRO X SUPERLIGHT2 Black")
  assert.equal(result.product_code, "")
  assert.equal(result.capacity, "")
  assert.equal(result.confirm_price_override, false)
  for (const key of ["rowId", "quantity", "unit_price", "discount_percent"]) assert.equal(result[key], row[key])
  assert.equal(row.product_name, "슈퍼라이트")
})
