"""users에 유일한 nullable supabase_uid를 더하고 google_sub를 nullable로 바꾼다(계획 5절).

기존 행은 그대로 두고 Supabase 로그인 사용자만 supabase_uid를 채운다. 새 표를 만들지 않으므로
metadata가 이미 만든 표(새 DB)에서는 아무 것도 하지 않는다.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261112_supabase_users"
down_revision = "20261111_trade_reviews"
branch_labels = None
depends_on = None


def columns(table):
    return {column["name"]: column for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    user_columns = columns("users")
    if "supabase_uid" not in user_columns:
        op.add_column("users", sa.Column("supabase_uid", sa.Uuid(), nullable=True))
    indices = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("users")}
    if "uq_users_supabase_uid" not in indices:
        op.create_index("uq_users_supabase_uid", "users", ["supabase_uid"], unique=True)
    if not user_columns["google_sub"]["nullable"]:
        naming = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
        with op.batch_alter_table("users", naming_convention=naming) as batch:
            batch.alter_column("google_sub", existing_type=sa.String(), nullable=True)


def downgrade():
    raise RuntimeError("데이터를 보존하는 전진 갱신만 지원합니다. 복구에는 갱신 전 백업을 사용하세요.")
