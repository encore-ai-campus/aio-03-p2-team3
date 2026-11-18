"""대화 소유권·실행 접수·화면 투영. 실제 그래프 상태는 공식 체크포인터에 저장한다."""
from sqlalchemy import Index, String, select
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base, Created, Owned, Updated, JSON_VALUE, User, utcnow
from app.graph.schemas import WorkflowError


class AgentConversation(Base, Owned, Created, Updated):
    __tablename__ = "agent_conversations"
    __table_args__ = (Index("ix_agent_user_updated", "user_id", "updated_at"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24), default="running")
    revision: Mapped[int] = mapped_column(default=1)
    view: Mapped[dict] = mapped_column(JSON_VALUE, default=dict)


def data(row):
    return {**row.view, "id": row.id, "title": row.title, "status": row.status,
            "revision": row.revision, "updated_at": row.updated_at.isoformat()}


def stop_progress(progress, stopped_at):
    steps = [{**step, "status": "interrupted"} if step["status"] == "running" else step
             for step in progress["steps"]]
    return {**progress, "finished_at": stopped_at.isoformat(), "steps": steps}


class ConversationStore:
    def __init__(self, database):
        self.database = database

    def list(self, owner):
        with self.database.session() as s:
            rows = s.scalars(select(AgentConversation).where(AgentConversation.user_id == owner)
                .order_by(AgentConversation.updated_at.desc()).limit(30))
            return [{key: data(row)[key] for key in ("id", "title", "status", "updated_at")} for row in rows]

    def get(self, owner, conversation_id):
        with self.database.session() as s:
            row = s.scalar(select(AgentConversation).where(AgentConversation.id == conversation_id,
                           AgentConversation.user_id == owner))
            if row is None:
                raise WorkflowError("workflow_not_found")
            return data(row)

    def claim(self, owner, conversation_id, *, title=None, revision=None):
        with self.database.session() as s:
            s.scalar(select(User.id).where(User.id == owner).with_for_update())
            row = s.scalar(select(AgentConversation).where(AgentConversation.id == conversation_id,
                           AgentConversation.user_id == owner).with_for_update())
            if title is None and row is None:
                raise WorkflowError("workflow_not_found")
            active = s.scalar(select(AgentConversation.id).where(AgentConversation.user_id == owner,
                              AgentConversation.status == "running").limit(1))
            if active:
                raise WorkflowError("agent_busy")
            if row is None:
                row = AgentConversation(id=conversation_id, user_id=owner, title=title[:120],
                    status="running", revision=1, view={"messages": [{"role": "user", "text": title}],
                                                       "results": [], "waiting": None, "error": None})
                s.add(row)
            else:
                if row.revision != revision:
                    raise WorkflowError("stale_conversation")
                row.revision += 1
                row.status = "running"
            row.view = {**row.view, "progress": {"started_at": utcnow().isoformat(), "steps": []}}
            s.flush()
            return data(row)

    def update_progress(self, owner, conversation_id, revision, steps):
        with self.database.session() as s:
            row = self._running(s, owner, conversation_id, revision)
            if row is not None:
                row.view = {**row.view, "progress": {**row.view["progress"], "steps": steps}}

    def finish(self, owner, conversation_id, revision, view, status):
        with self.database.session() as s:
            row = self._running(s, owner, conversation_id, revision)
            if row is not None:
                row.view = {**view, "progress": stop_progress(row.view["progress"], utcnow())}
                row.status = status

    @staticmethod
    def _running(session, owner, conversation_id, revision):
        return session.scalar(select(AgentConversation).where(AgentConversation.id == conversation_id,
            AgentConversation.user_id == owner, AgentConversation.revision == revision,
            AgentConversation.status == "running").with_for_update())

    def interrupt_running(self):
        # ponytail: 단일 앱 프로세스. 다중 프로세스 지원 시 공유 임대로 교체한다.
        with self.database.session() as s:
            for row in s.scalars(select(AgentConversation).where(AgentConversation.status == "running")):
                if "progress" in row.view:
                    row.view = {**row.view, "progress": stop_progress(row.view["progress"], row.updated_at)}
                row.status = "interrupted"
