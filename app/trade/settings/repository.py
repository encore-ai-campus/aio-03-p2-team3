"""사용자 설정 저장 및 문서 작성용 단가표·거래처·직인 조회.

회사 로고·직인은 비공개 Storage의 file_assets 이미지를 가리킨다(계획 9절). 업로드 검증은
app.trade.settings.operations(2MiB·PNG)이 하고 이 모듈은 Storage 저장·조회 원본 대조를 담당한다.
"""
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select

from app.db.models import CompanyBankAccount, CompanyBranding, CompanyProfile, Counterparty, FileAsset, PriceListItem, User
from app.files.storage import StorageError
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
                    "counterparties": counterparty_profiles(session, self.user_id),
                    "branding": {"has_logo": bool(branding and branding.logo_file_id),
                                 "has_seal": bool(branding and branding.seal_file_id),
                                 "logo_file_id": branding.logo_file_id if branding else None,
                                 "seal_file_id": branding.seal_file_id if branding else None}}

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

    def save_counterparty(self, values):
        with user_lock(self.database, self.user_id), self.database.session() as session:
            self._user(session)
            row = session.scalar(select(Counterparty).where(
                Counterparty.user_id == self.user_id, Counterparty.company_key == values["company_key"]))
            if row is None:
                row = Counterparty(user_id=self.user_id, company_key=values["company_key"])
                session.add(row)
            for key, value in values.items():
                setattr(row, key, value)
        return self.read()

    def save_branding(self, kind, content, content_hash, storage):
        if kind not in ("seal", "logo"):
            raise DocumentError("INVALID_IMAGE_KIND", "직인 또는 로고를 선택하세요", 422)
        if storage is None:
            raise DocumentError("STORAGE_NOT_CONFIGURED",
                                "SUPABASE_URL·SUPABASE_SECRET_KEY가 설정되지 않아 이미지를 저장할 수 없습니다.", 503)
        object_key = f"{self.user_id}/branding/{uuid4().hex}"
        try:
            storage.upload(object_key, content, "image/png")
        except StorageError as error:
            raise DocumentError("STORAGE_UNAVAILABLE", error.message, 503) from error
        # Storage 저장이 성공한 뒤에만 메타데이터를 확정한다(계약 16.3절). 이 SQL이 실패하면 위
        # 객체는 미참조로 남고 cleanup 명령이 정리한다.
        with user_lock(self.database, self.user_id), self.database.session() as session:
            self._user(session)
            asset = FileAsset(user_id=self.user_id, original_filename=f"{kind}.png", content_type="image/png",
                              size_bytes=len(content), sha256=content_hash, object_key=object_key)
            session.add(asset)
            session.flush()
            row = session.get(CompanyBranding, self.user_id)
            if row is None:
                row = CompanyBranding(user_id=self.user_id)
                session.add(row)
            if kind == "seal":
                row.seal_file_id = asset.id
            else:
                row.logo_file_id = asset.id
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


def branding_file_assets(session, user_id):
    """company_branding이 가리키는 (로고, 직인) file_assets 행. 소유자가 다른 파일은 없음으로 본다."""
    row = session.get(CompanyBranding, user_id)

    def owned(file_id):
        if file_id is None:
            return None
        asset = session.get(FileAsset, file_id)
        return asset if asset is not None and asset.user_id == user_id else None

    return owned(row.logo_file_id if row is not None else None), owned(row.seal_file_id if row is not None else None)


def download_verified_image(storage, asset: FileAsset) -> bytes:
    """Storage에서 이미지 bytes를 읽어 file_assets에 기록된 SHA-256과 대조한다(계획 9절).

    Storage 미설정·호출 실패·대조 불일치는 StorageError로 나간다. 이미지 손상을 성공으로 돌려주지 않는다.
    """
    if storage is None:
        raise StorageError("storage_not_configured",
                           "SUPABASE_URL·SUPABASE_SECRET_KEY가 설정되지 않아 이미지를 읽을 수 없습니다.")
    data = storage.download(asset.object_key)
    if sha256(data).hexdigest() != asset.sha256:
        raise StorageError("image_corrupted",
                           "저장된 회사 이미지가 기록과 일치하지 않습니다. 관리자에게 문의해 주세요.")
    return data


# 원본: reference/kekorea/Quotation_KEKOREA/agent/branding.py resolve_company_seal(반환 형식은 계약 15.4절)
def resolve_company_seal(user_id, *, database=None, storage=None):
    """company_branding이 가리키는 직인 PNG bytes를 Storage에서 꺼낸다(계획 9절).

    반환: (직인 bytes | None, 오류 문구 | None). 오류 문구는 화면 안내용이고 비밀값을 담지 않는다.
    Storage 미설정·호출 실패·원본 대조 불일치는 StorageError를 던진다(성공으로 처리하지 않는다).
    database를 주지 않으면 앱 기본 DB(app.db.engine.get_database)를 쓴다.
    """
    from app.db.engine import get_database

    db = database or get_database()
    with db.session() as session:
        _, asset = branding_file_assets(session, user_id)
        if asset is None:
            return None, "회사 직인이 업로드되지 않았습니다. 설정에서 직인을 업로드해 주세요."
        seal = download_verified_image(storage, asset)
    if not seal.startswith(PNG_MAGIC):
        return None, "저장된 회사 직인이 PNG 이미지가 아닙니다. 직인을 다시 업로드해 주세요."
    return seal, None


def resolve_company_logo(user_id, *, database=None, storage=None):
    """company_branding이 가리키는 로고 bytes(없으면 None). 실패는 resolve_company_seal과 같다."""
    from app.db.engine import get_database

    db = database or get_database()
    with db.session() as session:
        asset, _ = branding_file_assets(session, user_id)
        if asset is None:
            return None
        return download_verified_image(storage, asset)
