import { Link } from "react-router-dom"

const RECEIVED = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
  timeZone: "Asia/Seoul",
})
const FIELDS = { subject: "제목", body: "본문", sender: "발신자", all: "제목·발신자·본문" }
const REPLIES = { unanswered: "답장 발송 기록 없음", replied: "답장 발송 확인" }

function receivedTime(value) {
  return value ? RECEIVED.format(new Date(value)) : ""
}

export default function MailSearchResult({ data }) {
  const { search_scope: scope, threads, next_cursor: nextCursor } = data
  const range = [receivedTime(scope?.received_from) || "시작 제한 없음",
    receivedTime(scope?.received_before) || "종료 제한 없음"]
  return <section className="mail-search-result" aria-label="수신 메일 검색 결과">
    {scope && <div className="mail-search-scope">
      {scope.query && <span>{FIELDS[scope.field]} <b>“{scope.query}”</b></span>}
      {(scope.received_from || scope.received_before) && <span>{range.join(" ~ ")}{scope.received_before && " 미만"} · 한국 시간</span>}
      {REPLIES[scope.reply_status] && <span>{REPLIES[scope.reply_status]}</span>}
    </div>}
    {threads.length === 0
      ? <p>조건에 맞는 수신 메일이 없습니다.</p>
      : <ul className="mail-search-items">
        {threads.map(thread => <li key={thread.thread_id}>
          <div className="mail-search-item-heading">
            <Link to={`/inbox?thread=${encodeURIComponent(thread.thread_id)}`}>{thread.subject || "(제목 없음)"}</Link>
            {thread.reply_status && <span className="mail-search-state">{REPLIES[thread.reply_status]}</span>}
          </div>
          <div className="mail-search-meta">
            {thread.from_addr && <span>{thread.from_addr}</span>}
            {thread.received_at && <time dateTime={thread.received_at}>{receivedTime(thread.received_at)}</time>}
          </div>
          {thread.preview && <p>{thread.preview}</p>}
        </li>)}
      </ul>}
    {nextCursor && <p className="mail-search-next">이어서 다음 검색 결과를 요청할 수 있습니다.</p>}
  </section>
}
