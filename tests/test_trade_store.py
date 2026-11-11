"""무역 단가표·거래처 저장소 pytest(kekorea-port 3절 B, 계약 15.7절).

원본 tests/test_counterparties_api.py(Supabase REST 시험)는 계약 15.4절이 Supabase 접근을
없애고 `counterparties` 표 조회로 바꿨기 때문에, 그 의도(전용 디렉터리 조회·레코드 형태)를
DB 조회 시험으로 옮겼다. 가상 값만 쓴다.
"""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import Counterparty, PriceListItem, User
from app.trade.common.pricing import build_trade_catalog
from app.trade.settings.repository import counterparty_profiles, trade_price_rows


def test_domestic_rows_keep_user_item_uniqueness(database):
    with database.session() as session:
        session.add(PriceListItem(user_id=1, item_name="가상크림", unit="개", unit_price=1000))
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(PriceListItem(user_id=1, item_name="가상크림", unit="개", unit_price=2000))


def test_trade_rows_use_role_currency_party_uniqueness(database):
    def trade_row(**overrides):
        base = dict(user_id=1, item_name="Test Cream", role="purchase", currency="KRW",
                    unit_price_text="8000", party_key="ACME_SUPPLIER")
        base.update(overrides)
        return PriceListItem(**base)

    with database.session() as session:
        session.add(trade_row())
        session.add(trade_row(currency="USD", unit_price_text="6"))  # 통화가 다르면 다른 행
        session.add(trade_row(role="sale", currency="USD", party_key="ACME_BUYER"))
        session.add(trade_row(party_key=""))  # 공통 가격 행
        session.add(PriceListItem(user_id=1, item_name="Test Cream", unit="개", unit_price=1000))  # 국내 행과 공존
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(trade_row())  # 같은 (품목, role, 통화, party_key) 조합


def test_trade_price_rows_are_isolated_per_user_and_feed_catalog(database):
    rows = [
        dict(user_id=1, item_name="Test Cream", role="purchase", currency="KRW",
             unit_price_text="1,000", party_key="ACME_SUPPLIER", capacity="50ml",
             product_code="T-1", price_basis="per PCS"),
        dict(user_id=1, item_name="Test Cream", role="sale", currency="USD",
             unit_price_text="10.25", party_key="ACME_BUYER"),
    ]
    with database.session() as session:
        session.add(User(id=2, google_sub="fake-sub-2", email="other@example.invalid"))
    with database.session() as session:
        session.add_all([PriceListItem(**row) for row in rows])
        session.add(PriceListItem(user_id=1, item_name="국내크림", unit="개", unit_price=900))
        session.add(PriceListItem(user_id=2, item_name="Test Cream", role="purchase",
                                  currency="KRW", unit_price_text="9999", party_key="OTHER"))
    with database.session() as session:
        mine = trade_price_rows(session, 1)
        other = trade_price_rows(session, 2)
    assert [row["item_name"] for row in mine] == ["Test Cream", "Test Cream"]  # 국내 행은 빠진다
    assert mine[0]["unit_price_text"] == "1,000"
    catalog = build_trade_catalog(mine)
    assert len(catalog["products"]) == 1
    assert catalog["products"][0]["id"] == mine[0]["id"]
    assert catalog["products"][0]["capacity"] == "50ml"
    assert len(catalog["purchase_prices"]) == 1 and len(catalog["buyer_prices"]) == 1
    assert [row["party_key"] for row in other] == ["OTHER"]


def test_counterparty_profiles_isolated_per_user_and_shaped_for_apply(database):
    with database.session() as session:
        session.add(User(id=2, google_sub="fake-sub-2", email="other@example.invalid"))
    with database.session() as session:
        session.add(Counterparty(user_id=1, company_key="ACME_BUYER", legal_name="ACME BUYER PTE LTD",
                                 aliases=["Acme Buyer"], address="Test Address",
                                 default_ship_to="Test Delivery", ship_to_phone="N/A"))
        session.add(Counterparty(user_id=2, company_key="ACME_BUYER", legal_name="OTHER BUYER",
                                 aliases=[]))
    with database.session() as session:
        mine = counterparty_profiles(session, 1)
        other = counterparty_profiles(session, 2)
    assert len(mine) == 1 and len(other) == 1
    assert mine[0]["legal_name"] == "ACME BUYER PTE LTD"
    assert mine[0]["aliases"] == ["Acme Buyer"]
    assert set(mine[0]) == set(  # 원본 FIELDS 키를 그대로 돌려준다
        ("company_key", "legal_name", "aliases", "address", "contact", "phone",
         "email", "registration_details", "default_ship_to", "ship_to_phone"))
    # 조회 결과는 apply_company_profiles 입력으로 바로 쓸 수 있다.
    from app.trade.common.counterparties import apply_company_profiles
    draft = {"document_type": "PI", "buyer": {}, "seller": {"legal_name": "Testworks Trading Co"}}
    apply_company_profiles(draft, mine, prompt="Acme Buyer 인보이스 작성")
    assert draft["buyer"]["legal_name"] == "ACME BUYER PTE LTD"
    assert draft["ship_to"] == "Test Delivery / Tel: N/A"


def test_counterparty_company_key_is_unique_per_user(database):
    with database.session() as session:
        session.add(Counterparty(user_id=1, company_key="ACME_BUYER", legal_name="ACME BUYER PTE LTD"))
    with database.session() as session:
        session.add(User(id=2, google_sub="fake-sub-2", email="other@example.invalid"))
    with database.session() as session:
        session.add(Counterparty(user_id=2, company_key="ACME_BUYER", legal_name="OTHER"))
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(Counterparty(user_id=1, company_key="ACME_BUYER", legal_name="중복"))
