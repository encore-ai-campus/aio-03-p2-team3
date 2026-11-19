import { useState } from "react"
import { Link } from "react-router-dom"
import { downloadFile } from "../api"

const dateFormat = new Intl.DateTimeFormat("ko-KR", {
  month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  timeZone: "Asia/Seoul", timeZoneName: "short",
})
const status = { pending: "답장 대기", due: "기한까지 답장 없음", replied: "답장 도착", cancelled: "알림 취소" }

function threadUrl(id) {
  return `/inbox?thread=${encodeURIComponent(id)}`
}

export function AttachmentResult({ files, token, onError }) {
  const [busy, setBusy] = useState(null)

  async function download(file) {
    setBusy(file.part_id)
    try {
      await downloadFile(file, token)
    } catch (error) {
      onError(error.message)
    } finally {
      setBusy(null)
    }
  }

  return <section className="directory-result" aria-label="원본 메일 첨부">
    {files.length ? <ul className="directory-cards">{files.map(file => <li className="directory-card" key={file.part_id}>
      <div className="directory-price-heading">
        <div><h3>{file.filename}</h3><span>{file.media_type || "파일"}{Number.isInteger(file.size) && ` · ${file.size.toLocaleString("ko-KR")} B`}</span></div>
        <button type="button" className="doc-link" disabled={busy !== null} onClick={() => download(file)}>
          {busy === file.part_id ? "받는 중" : "원본 받기"}
        </button>
      </div>
    </li>)}</ul> : <p>이 원본 메일에는 첨부가 없습니다.</p>}
  </section>
}

export function FollowupResult({ data }) {
  return <section className="directory-result" aria-label="메일 후속 알림">
    {data.followups.length ? <ul className="directory-cards">{data.followups.map(item => <li className="directory-card" key={item.id}>
      <div className="directory-price-heading">
        <div><h3>{item.subject || "(제목 없음)"}</h3><span>{status[item.status]}</span></div>
        <Link className="doc-link" to={threadUrl(item.thread_id)}>메일 열기</Link>
      </div>
      <p>기준 발송 {dateFormat.format(new Date(item.anchor_at))}</p>
      <p>확인 기한 {dateFormat.format(new Date(item.due_at))}</p>
    </li>)}</ul> : <p>등록한 후속 알림이 없습니다.</p>}
    {data.next_cursor && <p>다음 알림 목록을 요청할 수 있습니다.</p>}
  </section>
}

export function SentMailResult({ data }) {
  return <section className="directory-result" aria-label="발송한 메일">
    {data.sent_threads.length ? <ul className="directory-cards">{data.sent_threads.map(item => <li className="directory-card" key={item.thread_id}>
      <div className="directory-price-heading">
        <div><h3>{item.subject || "(제목 없음)"}</h3><span>{item.to_addrs.join(", ")} · {dateFormat.format(new Date(item.received_at))}</span></div>
        <Link className="doc-link" to={threadUrl(item.thread_id)}>메일 열기</Link>
      </div>
    </li>)}</ul> : <p>수집된 발송 메일 중 일치하는 결과가 없습니다.</p>}
    {data.has_more && <p>검색어를 좁히면 다른 결과를 확인할 수 있습니다.</p>}
  </section>
}
