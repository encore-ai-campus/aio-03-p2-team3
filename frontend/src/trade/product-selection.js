// 수량·거래 조건·입력 단가는 보존하고 SKU와 단가 사용 확인은 새로 검증한다.
export function selectProduct(row, product) {
  return { ...row, product_name: product.item_name, product_code: product.source_code ?? "",
    capacity: product.capacity ?? "", confirm_price_override: false }
}
