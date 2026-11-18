const ROLES = { sale: "판매", purchase: "매입" }

function Fields({ rows }) {
  return <dl className="directory-fields">
    {rows.filter(([, value]) => value).map(([label, value]) => <div key={label}>
      <dt>{label}</dt><dd>{value}</dd>
    </div>)}
  </dl>
}

export function CounterpartyResult({ data }) {
  const { counterparties, total } = data
  return <section className="directory-result" aria-label="등록 거래처 조회 결과">
    {counterparties.length === 0 && <p>일치하는 등록 거래처가 없습니다.</p>}
    {total > 1 && <p>일치하는 거래처 {total}건입니다. 확인할 회사를 골라 주세요.</p>}
    <ul className="directory-cards">
      {counterparties.map(party => <li className="directory-card" key={party.company_key}>
        <h3>{party.legal_name}</h3>
        <Fields rows={[["담당자", party.contact], ["이메일", party.email],
          ["전화", party.phone], ["주소", party.address]]} />
        {!(party.contact || party.email || party.phone || party.address) && <p>등록된 연락처가 없습니다.</p>}
      </li>)}
    </ul>
    {total > counterparties.length && <p>처음 {counterparties.length}건을 표시합니다.</p>}
  </section>
}

export function TradePriceResult({ data }) {
  if (data.price_status === "choose_counterparty") return <CounterpartyResult data={data} />
  return <section className="directory-result" aria-label="등록 단가 조회 결과">
    {data.prices.length === 0 && <p>조건에 맞는 등록 단가가 없습니다.</p>}
    <ul className="directory-cards">
      {data.prices.map(price => <li className="directory-card" key={price.id}>
        <div className="directory-price-heading">
          <div><h3>{price.item_name}</h3>{price.product_code && <span>{price.product_code}</span>}</div>
          <strong>{price.currency} {price.unit_price}{price.unit && <small> / {price.unit}</small>}</strong>
        </div>
        <Fields rows={[["구분", ROLES[price.role]], ["가격 기준", price.price_basis],
          ["규격", price.capacity], ["적용 대상", price.scope === "common" ? "공통 단가" : price.counterparty || "거래처 단가"]]} />
      </li>)}
    </ul>
    {data.total > data.prices.length && <p>전체 {data.total}건 중 {data.prices.length}건을 표시합니다.</p>}
  </section>
}
