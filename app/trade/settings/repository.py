from sqlalchemy import select

from app.db.models import CompanyBankAccount, CompanyBranding, CompanyProfile, PriceListItem, User
from app.services.locks import user_lock
from app.trade.common.models import DocumentError
from app.trade.common.repository import BANK_FIELDS, ISSUER_FIELDS


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
