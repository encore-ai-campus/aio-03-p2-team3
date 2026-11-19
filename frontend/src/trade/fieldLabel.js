export const LABELS = {
  product_family: "상품군", document_number: "문서번호", currency: "통화", incoterms: "납품 조건",
  payment_terms: "지급 조건", ship_to: "배송지", bill_to: "청구지", country_of_origin: "원산지",
  shipment_reference: "선적 참조", container_count: "컨테이너 수", actual_package_count: "포장 수",
  declared_net_weight_kg: "원본 순중량 (kg)", declared_gross_weight_kg: "원본 총중량 (kg)",
  declared_volume_cbm: "원본 부피 (CBM)", declared_total_quantity: "원본 총수량",
  declared_total_quantity_unit: "원본 수량 단위", legal_name: "회사명 (영문)", address: "주소 (영문)",
  contact: "담당자", phone: "전화", email: "이메일", product_name: "품목명 (영문)",
  product_code: "상품 코드", capacity: "용량·규격", quantity: "수량", unit: "단위",
  unit_price: "단가", discount_percent: "할인율 (%)", free_quantity: "무상 수량", price_basis: "가격 기준",
}

export function fieldLabel(path) {
  const [first, index, key] = path.split(".")
  if (first === "buyer" || first === "seller") return `${first === "buyer" ? "구매자" : "판매자"} · ${LABELS[index] ?? index}`
  if ((first === "items" || first === "packages") && key) return `${first === "items" ? "품목" : "포장"} ${Number(index) + 1} · ${LABELS[key] ?? key}`
  return LABELS[first] ?? first
}
