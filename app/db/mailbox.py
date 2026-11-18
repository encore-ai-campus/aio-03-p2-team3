"""본인 메일·분류·후보 조회. HTTP와 모델 호출은 이 모듈에 두지 않는다."""
from sqlalchemy import select, update, func, or_

from app.db.models import (ProcessedMessage, ThreadMessage, ReplyCandidate, CompanyProfile,
                           GmailWatch, GoogleToken, TradeDocument, Quote)


def _time(value):
    return value.isoformat() if value else None


class MailStore:
    def __init__(self, database):
        self.database = database

    def connected(self, owner):
        with self.database.session() as s:
            token, watch = s.get(GoogleToken, owner), s.get(GmailWatch, owner)
            return bool(token and token.refresh_token_enc and watch and watch.status != "stopped"
                        and watch.last_error not in {"token_expired", "history_expired"})

    def context(self, owner):
        with self.database.session() as s:
            company = s.get(CompanyProfile, owner)
            return {"company_name": company.company_name if company else None,
                    "legal_name": company.legal_name_en if company else None}

    def stamp(self, owner):
        with self.database.session() as s:
            watch = s.get(GmailWatch, owner)
            return (watch.topic, watch.last_renewed_at) if watch else None

    def get(self, owner, message_id):
        with self.database.session() as s:
            row = s.scalar(select(ProcessedMessage).where(
                ProcessedMessage.user_id == owner, ProcessedMessage.gmail_message_id == message_id))
            if row is None:
                return None
            message = s.scalar(select(ThreadMessage).where(ThreadMessage.user_id == owner,
                               ThreadMessage.gmail_message_id == message_id))
            return {"id": row.id, "gmail_message_id": row.gmail_message_id, "thread_id": row.thread_id,
                    "status": row.status, "triage": row.triage, "run_id": row.run_id, "notice": row.notice,
                    "email": {"gmail_message_id": row.gmail_message_id, "thread_id": row.thread_id,
                              "rfc_message_id": None, "from_addr": message.from_addr,
                              "from_name": None, "to_addrs": message.to_addrs, "subject": message.subject,
                              "body_text": message.body_text, "received_at": _time(message.sent_at),
                              "direction": "in"} if message else None}

    def mark(self, owner, message_id, status, triage, notice=None):
        with self.database.session() as s:
            row = s.scalar(select(ProcessedMessage).where(
                ProcessedMessage.user_id == owner, ProcessedMessage.gmail_message_id == message_id))
            if row and row.status != "sent":
                row.status, row.triage, row.notice = status, triage, notice

    def candidates_exist(self, owner, message_id):
        with self.database.session() as s:
            return s.scalar(select(ReplyCandidate.id).where(ReplyCandidate.user_id == owner,
                            ReplyCandidate.source_message_id == message_id).limit(1)) is not None

    def pending(self):
        with self.database.session() as s:
            return list(s.execute(select(ProcessedMessage.user_id, ProcessedMessage.gmail_message_id)
                        .join(GmailWatch, GmailWatch.user_id == ProcessedMessage.user_id)
                        .join(GoogleToken, GoogleToken.user_id == ProcessedMessage.user_id)
                        .where(ProcessedMessage.status == "processing", ProcessedMessage.triage.is_not(None))
                        .where(GmailWatch.status != "stopped",
                               GoogleToken.refresh_token_enc.is_not(None), GoogleToken.refresh_token_enc != "")
                        .order_by(ProcessedMessage.id).limit(100)))

    def message_key(self, owner, row_id):
        with self.database.session() as s:
            return s.scalar(select(ProcessedMessage.gmail_message_id).where(
                ProcessedMessage.id == row_id, ProcessedMessage.user_id == owner))

    def threads(self, owner, *, status=None, query="", cursor=None, limit=30):
        with self.database.session() as s:
            latest = select(func.max(ProcessedMessage.id)).where(ProcessedMessage.user_id == owner,
                     or_(ProcessedMessage.skip_reason.is_(None), ProcessedMessage.skip_reason == "intent_ignore")
                     ).group_by(ProcessedMessage.thread_id)
            stmt = select(ProcessedMessage, ThreadMessage).outerjoin(ThreadMessage,
                (ThreadMessage.user_id == owner) &
                (ThreadMessage.gmail_message_id == ProcessedMessage.gmail_message_id)
            ).where(ProcessedMessage.user_id == owner, ProcessedMessage.id.in_(latest))
            if status:
                stmt = stmt.where(ProcessedMessage.status == status)
            if query:
                # LIKE 제어 문자는 검색 문자열 그대로 취급한다.
                needle = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                stmt = stmt.where(or_(ThreadMessage.subject.ilike(needle, escape="\\"),
                                      ThreadMessage.from_addr.ilike(needle, escape="\\")))
            if cursor:
                stmt = stmt.where(ProcessedMessage.id < cursor)
            rows = list(s.execute(stmt.order_by(ProcessedMessage.id.desc()).limit(limit + 1)))
            items = [{"id": p.id, "thread_id": p.thread_id, "status": p.status,
                      "subject": m.subject if m else "(제목 없음)", "from_addr": m.from_addr if m else "",
                      "preview": m.body_text[:120] if m else "", "received_at": _time(p.received_at),
                      "notice": p.notice, "triage": p.triage} for p, m in rows[:limit]]
            # 상태 탭 건수: 목록과 같은 '스레드별 최신 처리' 기준으로 센다.
            counts = dict(s.execute(select(ProcessedMessage.status, func.count())
                              .where(ProcessedMessage.user_id == owner,
                                     ProcessedMessage.id.in_(latest))
                              .group_by(ProcessedMessage.status)).all())
            token, watch = s.get(GoogleToken, owner), s.get(GmailWatch, owner)
            return {"items": items, "next_cursor": items[-1]["id"] if len(rows) > limit else None,
                    "status_counts": counts,
                    "connection": {"connected": bool(token and token.refresh_token_enc),
                                   "watch": watch.status if watch else "stopped"}}

    def thread(self, owner, thread_id):
        with self.database.session() as s:
            messages = list(s.scalars(select(ThreadMessage).where(ThreadMessage.user_id == owner,
                            ThreadMessage.thread_id == thread_id).order_by(ThreadMessage.sent_at, ThreadMessage.id)))
            processing = list(s.scalars(select(ProcessedMessage).where(ProcessedMessage.user_id == owner,
                              ProcessedMessage.thread_id == thread_id,
                              or_(ProcessedMessage.skip_reason.is_(None), ProcessedMessage.skip_reason == "intent_ignore")
                              ).order_by(ProcessedMessage.id)))
            if not messages and not processing:
                return None
            candidates = list(s.scalars(select(ReplyCandidate).where(ReplyCandidate.user_id == owner,
                              ReplyCandidate.thread_id == thread_id).order_by(ReplyCandidate.id)))
            return {"thread_id": thread_id,
                    "messages": [{"id": m.id, "direction": m.direction, "from_addr": m.from_addr,
                                  "to_addrs": m.to_addrs, "subject": m.subject, "body": m.body_text,
                                  "sent_at": _time(m.sent_at)} for m in messages],
                    "processing": [{"id": p.id, "status": p.status, "triage": p.triage,
                                    "notice": p.notice, "run_id": p.run_id} for p in processing],
                    "candidates": [self._candidate(s, owner, c) for c in candidates]}

    def candidate(self, owner, candidate_id):
        with self.database.session() as s:
            row = s.scalar(select(ReplyCandidate).where(ReplyCandidate.id == candidate_id,
                           ReplyCandidate.user_id == owner))
            return self._candidate(s, owner, row) if row else None

    def edit_candidate(self, owner, candidate_id, *, subject, body, expected_subject, expected_body):
        """Only update an unsent owned candidate when the editor used the latest content."""
        with self.database.session() as s:
            return bool(s.execute(
                update(ReplyCandidate).where(
                    ReplyCandidate.id == candidate_id,
                    ReplyCandidate.user_id == owner,
                    ReplyCandidate.status.in_(("pending", "send_failed")),
                    ReplyCandidate.subject == expected_subject,
                    ReplyCandidate.body == expected_body,
                ).values(subject=subject, body=body)
            ).rowcount)

    def quote(self, owner, quote_id):
        with self.database.session() as s:
            row = s.scalar(select(Quote).where(Quote.user_id == owner, Quote.id == quote_id))
            return {"status": row.status, "draft": row.draft} if row else None

    def complete_quote(self, owner, quote_id, before, draft):
        with self.database.session() as s:
            return bool(s.execute(update(Quote).where(
                Quote.user_id == owner, Quote.id == quote_id, Quote.status == "needs_price",
                Quote.draft == before,
            ).values(draft=draft, status=draft["status"])).rowcount)

    @staticmethod
    def _candidate(s, owner, c):
        document = s.get(TradeDocument, c.trade_doc_id) if c.trade_doc_id else None
        quote = s.get(Quote, c.quote_id) if c.quote_id else None
        document = document if document and document.user_id == owner else None
        quote = quote if quote and quote.user_id == owner else None
        # 원 단위 정수를 브라우저 Number 정밀도로 반올림하지 않는다.
        quote_draft = None
        if quote:
            quote_draft = {**quote.draft, "lines": [
                {**line, **{key: str(line[key]) if line.get(key) is not None else None
                            for key in ("quantity", "unit_price", "amount")}}
                for line in quote.draft["lines"]],
                **{key: str(quote.draft[key]) if quote.draft.get(key) is not None else None
                   for key in ("supply_amount", "vat", "total")}}
        return {"id": c.id, "label": c.label, "subject": c.subject, "body": c.body,
                "kind": c.kind, "status": c.status, "needs_review": c.needs_review,
                "notice": c.notice, "quote_id": c.quote_id, "trade_doc_id": c.trade_doc_id,
                "thread_id": c.thread_id, "source_message_id": c.source_message_id,
                "document": {"kind": document.doc_kind, "status": document.status,
                             "revision": document.revision, "draft": document.draft} if document else
                            {"kind": "quote", "status": quote.status, "draft": quote_draft} if quote else None}
