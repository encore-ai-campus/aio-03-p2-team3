"""사용자 설정 저장 및 문서 작성용 단가표·거래처·직인 조회."""
import hashlib

from sqlalchemy import select

from app.db.models import CompanyBankAccount, CompanyBranding, CompanyProfile, Counterparty, PriceListItem, User
from app.services.locks import user_lock
from app.trade.common.models import DocumentError
from app.trade.settings.models import BANK_FIELDS, ISSUER_FIELDS


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class SQLSettings:
    def __init__(self, database, user_id):
        self.database, self.user_id = database, user_id

    def _user(self, session):
        if session.scalar(select(User).where(User.id == self.user_id).with_for_update()) is None:
            raise DocumentError("USER_NOT_FOUND", "로그인이 필요합니다", 401)

    def read(self):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            company = session.get(CompanyProfile, self.user_id)
            branding = session.get(CompanyBranding, self.user_id)
            prices = session.scalars(select(PriceListItem).where(
                PriceListItem.user_id == self.user_id, PriceListItem.role.is_not(None)).order_by(PriceListItem.id)).all()
            banks = session.scalars(select(CompanyBankAccount).where(
                CompanyBankAccount.user_id == self.user_id).order_by(CompanyBankAccount.currency)).all()
            return {"company": {key: getattr(company, key) for key in ISSUER_FIELDS} if company else None,
                    "banks": [{"currency": bank.currency, **{key: getattr(bank, key) for key in BANK_FIELDS}} for bank in banks],
                    "prices": [{"id": price.id, "unit_price": price.unit_price_text,
                                **{key: getattr(price, key) for key in ("item_name", "role", "currency", "party_key",
                                   "unit", "price_basis", "product_code", "capacity")}} for price in prices],
                    "branding": {"has_logo": bool(branding and branding.logo),
                                 "has_seal": bool(branding and branding.seal)}}

    def save_company(self, values):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            self._user(session)
            row = session.get(CompanyProfile, self.user_id)
            if row is None:
                row = CompanyProfile(user_id=self.user_id)
                session.add(row)
            for key, value in values.items():
                setattr(row, key, value)
        return self.read()

    def save_bank(self, currency, values):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            self._user(session)
            row = session.scalar(select(CompanyBankAccount).where(
                CompanyBankAccount.user_id == self.user_id, CompanyBankAccount.currency == currency))
            if row is None:
                row = CompanyBankAccount(user_id=self.user_id, currency=currency)
                session.add(row)
            for key, value in values.items():
                setattr(row, key, value)
        return self.read()

    def save_price(self, values):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            self._user(session)
            row = session.scalar(select(PriceListItem).where(
                PriceListItem.user_id == self.user_id,
                *[getattr(PriceListItem, key) == values[key] for key in ("item_name", "role", "currency", "party_key")]))
            if row is None:
                row = PriceListItem(user_id=self.user_id, item_name=values["item_name"])
                session.add(row)
            for key, value in values.items():
                setattr(row, key, value)
        return self.read()

    def save_branding(self, kind, content, content_hash):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            self._user(session)
            row = session.get(CompanyBranding, self.user_id)
            if row is None:
                row = CompanyBranding(user_id=self.user_id)
                session.add(row)
            if kind == "seal":
                row.seal, row.seal_sha256 = content, content_hash
            elif kind == "logo":
                row.logo = content
            else:
                raise DocumentError("INVALID_IMAGE_KIND", "직인 또는 로고를 선택하세요", 422)
        return self.read()


# 문서 작성에서 공유하는 설정 조회. 호출자가 지정한 사용자 범위만 읽는다.
def trade_price_rows(session, user_id):
    """본인 무역 단가 행을 `build_trade_catalog` 입력(dict) 목록으로 돌려준다."""
    rows = session.scalars(select(PriceListItem).where(
        PriceListItem.user_id == user_id, PriceListItem.role.is_not(None),
    ).order_by(PriceListItem.id)).all()
    return [{"id": row.id, "item_name": row.item_name, "unit": row.unit, "role": row.role,
             "currency": row.currency, "price_basis": row.price_basis,
             "product_code": row.product_code, "capacity": row.capacity,
             "unit_price_text": row.unit_price_text, "party_key": row.party_key}
            for row in rows]


def counterparty_profiles(session, user_id):
    """본인 거래처를 `apply_company_profiles` 입력(원본 FIELDS 키) 목록으로 돌려준다."""
    rows = session.scalars(select(Counterparty).where(
        Counterparty.user_id == user_id,
    ).order_by(Counterparty.company_key)).all()
    return [{"company_key": row.company_key, "legal_name": row.legal_name,
             "aliases": row.aliases if isinstance(row.aliases, list) else [],
             "address": row.address, "contact": row.contact, "phone": row.phone,
             "email": row.email, "registration_details": row.registration_details,
             "default_ship_to": row.default_ship_to, "ship_to_phone": row.ship_to_phone}
            for row in rows]


# 원본: reference/kekorea/Quotation_KEKOREA/agent/branding.py resolve_company_seal(반환 형식은 계약 15.4절)
def resolve_company_seal(user_id, *, database=None):
    """company_branding 표에서 사용자별 직인 PNG bytes를 꺼낸다.

    반환: (직인 bytes | None, 오류 문구 | None). 오류 문구는 화면 안내용이고 비밀값을 담지 않는다.
    database를 주지 않으면 앱 기본 DB(app.db.engine.get_database)를 쓴다.
    """
    from app.db.engine import get_database
    from app.db.models import CompanyBranding

    db = database or get_database()
    with db.session() as session:
        row = session.get(CompanyBranding, user_id)
        seal = row.seal if row is not None else None
        expected = row.seal_sha256 if row is not None else None
    if not seal:
        return None, "회사 직인이 업로드되지 않았습니다. 설정에서 직인을 업로드해 주세요."
    if not seal.startswith(PNG_MAGIC):
        return None, "저장된 회사 직인이 PNG 이미지가 아닙니다. 직인을 다시 업로드해 주세요."
    if not expected:
        return None, "직인 대조값(SHA-256)이 저장되어 있지 않습니다. 직인을 다시 업로드해 주세요."
    if hashlib.sha256(seal).hexdigest() != expected:
        return None, "저장된 직인이 업로드할 때의 값(SHA-256)과 다릅니다. 직인을 다시 업로드해 주세요."
    return seal, None
