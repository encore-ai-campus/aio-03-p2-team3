"""기존 국내 견적 DB와 1차 무역 이식 DB를 모두 갱신한다."""
from alembic import op
import sqlalchemy as sa

revision = "20261111_trade_schema"
down_revision = None
branch_labels = None
depends_on = None


def columns(table):
    return {column["name"]: column for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    company_columns = columns("company_profiles")
    for name, kind in (("legal_name_en", sa.String()), ("address", sa.Text()),
                       ("phone", sa.String()), ("email", sa.String()),
                       ("registration_details", sa.Text())):
        if name not in company_columns:
            op.add_column("company_profiles", sa.Column(name, kind, nullable=True))

    if "trade_doc_id" not in columns("reply_candidates"):
        if op.get_bind().dialect.name == "sqlite":
            # SQLite의 nullable REFERENCES 열은 원래 ADD COLUMN으로 추가할 수 있다.
            # 후보를 참조하는 승인 이력을 보존하도록 이 표는 재구축하지 않는다.
            op.execute("ALTER TABLE reply_candidates ADD COLUMN trade_doc_id INTEGER REFERENCES trade_documents(id)")
        else:
            op.add_column("reply_candidates", sa.Column(
                "trade_doc_id", sa.Integer(), sa.ForeignKey("trade_documents.id"), nullable=True))

    prices = columns("price_list_items")
    constraints = sa.inspect(op.get_bind()).get_unique_constraints("price_list_items")
    additions = {"role": sa.String(), "currency": sa.String(3), "price_basis": sa.String(),
                 "product_code": sa.String(), "capacity": sa.String(),
                 "unit_price_text": sa.String(), "party_key": sa.String()}
    obsolete = [constraint for constraint in constraints
                if constraint["column_names"] == ["user_id", "item_name"]]
    if any(name not in prices for name in additions) or obsolete or not prices["unit_price"]["nullable"]:
        naming = {"uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s"}
        with op.batch_alter_table("price_list_items", naming_convention=naming) as batch:
            for name, kind in additions.items():
                if name not in prices:
                    batch.add_column(sa.Column(name, kind, nullable=True))
            if not prices["unit_price"]["nullable"]:
                batch.alter_column("unit_price", existing_type=sa.BigInteger(), nullable=True)
            for constraint in obsolete:
                batch.drop_constraint(constraint["name"] or "uq_price_list_items_user_id_item_name", type_="unique")
    indices = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("price_list_items")}
    for name, keys, condition in (
        ("uq_price_list_items_domestic", ["user_id", "item_name"], "role IS NULL"),
        ("uq_price_list_items_trade", ["user_id", "item_name", "role", "currency", "party_key"], "role IS NOT NULL"),
    ):
        if name not in indices:
            op.create_index(name, "price_list_items", keys, unique=True,
                            sqlite_where=sa.text(condition), postgresql_where=sa.text(condition))

    if "revision" not in columns("trade_documents"):
        op.add_column("trade_documents", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))


def downgrade():
    raise RuntimeError("데이터를 보존하는 전진 갱신만 지원합니다. 복구에는 갱신 전 백업을 사용하세요.")
