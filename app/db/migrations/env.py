"""접속 정보는 앱의 기존 연결로만 전달받는다(키/URL을 파일에 저장하지 않음)."""
from alembic import context

connection = context.config.attributes["connection"]
configuration = {"connection": connection}
if connection.dialect.name == "postgresql":
    # Supabase의 auth·storage 스키마와 구분해 리비전 표는 public에 둔다(계획 4절).
    configuration["version_table_schema"] = "public"
context.configure(**configuration)
with context.begin_transaction():
    context.run_migrations()
