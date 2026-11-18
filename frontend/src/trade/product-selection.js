// 수량·거래 조건·입력 단가는 보존하고 상품 선택에 따른 등록 품목 확인은 다시 받는다.
export function selectProduct(row, product) {
  return { ...row, product_name: product.item_name, product_code: product.source_code ?? "",
    capacity: product.capacity ?? "", confirm_price_override: false, confirm_product_override: false }
}
