"""사용자별 암호화 OpenAI 키. 기존 사용자·메일·승인 데이터는 바꾸지 않는다."""
from alembic import op
from app.db.models import UserOpenAIKey

revision = "20261112_user_openai_keys"
down_revision = "20261111_trade_reviews"
branch_labels = None
depends_on = None


def upgrade():
    UserOpenAIKey.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("데이터를 보존하려면 갱신 전 백업으로 복구하세요")
