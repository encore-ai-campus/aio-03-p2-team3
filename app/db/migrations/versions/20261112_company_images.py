"""회사 로고·직인을 file_assets 이미지로 가리키는 열을 더한다(계획 9절).

company_branding·trade_proposals에 nullable 파일 ID 열만 추가한다. 기존 바이너리 열은
backfill(app.trade.settings.backfill) 검증 뒤 22절에서 따로 삭제한다. 새 DB에서는
metadata.create_all이 이미 만든 열이므로 아무 것도 하지 않는다.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261112_company_images"
down_revision = "20261112_supabase_users"
branch_labels = None
depends_on = None


def columns(table):
    return {column["name"]: column for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    for table in ("company_branding", "trade_proposals"):
        existing = columns(table)
        for name in ("logo_file_id", "seal_file_id"):
            if name not in existing:
                op.add_column(table, sa.Column(name, sa.Integer(),
                                               sa.ForeignKey("file_assets.id"), nullable=True))


def downgrade():
    raise RuntimeError("데이터를 보존하는 전진 갱신만 지원합니다. 복구에는 갱신 전 백업을 사용하세요.")
