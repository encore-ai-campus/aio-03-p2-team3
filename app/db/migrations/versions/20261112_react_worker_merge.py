"""Supabase 전환과 사용자별 AI 실행기의 데이터 보존 갱신 경로를 합친다."""

revision = "20261112_react_worker_merge"
down_revision = ("20261112_issued_artifacts", "20261112_worker_delivery")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    raise RuntimeError("데이터를 보존하는 전진 갱신만 지원합니다. 백업으로 복구하세요.")
