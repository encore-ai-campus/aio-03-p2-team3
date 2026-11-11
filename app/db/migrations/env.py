"""접속 정보는 앱의 기존 연결로만 전달받는다(키/URL을 파일에 저장하지 않음)."""
from alembic import context

connection = context.config.attributes["connection"]
context.configure(connection=connection)
with context.begin_transaction():
    context.run_migrations()
