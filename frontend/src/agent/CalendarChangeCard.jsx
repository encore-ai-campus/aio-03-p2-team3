import { shiftDateKey } from "../calendar/useCalendarEvents"

function readableTime(value) {
  const [day, hour] = value.split("T")
  return { day, clock: hour.slice(0, 5), offset: hour.endsWith("Z") ? "UTC" : `UTC${hour.slice(-6)}` }
}

export function CalendarInterval({ value }) {
  if (value.all_day) {
    const lastDay = shiftDateKey(value.end, -1)
    return <span>{value.start === lastDay ? value.start : `${value.start} ~ ${lastDay}`} · 종일</span>
  }
  const start = readableTime(value.start)
  const end = readableTime(value.end)
  if (start.day === end.day && start.offset === end.offset) {
    return <span><time dateTime={value.start}>{start.day} {start.clock}</time>
      {" ~ "}<time dateTime={value.end}>{end.clock}</time> <small>{end.offset}</small></span>
  }
  return <span><time dateTime={value.start}>{start.day} {start.clock} {start.offset}</time>
    {" ~ "}<time dateTime={value.end}>{end.day} {end.clock} {end.offset}</time></span>
}

export function CalendarChangeCard({ action }) {
  const { payload } = action
  const original = payload.event
  const initial = original || { ...payload.slot, all_day: false }
  return <div className="calendar-action-card">
    <h3>{original?.summary || payload.query?.title || "(제목 없음)"}</h3>
    <dl>
      <div><dt>{original ? "기존 일정" : "등록 시각"}</dt><dd><CalendarInterval value={initial} /></dd></div>
      {payload.new_time && <div><dt>변경 시각</dt><dd><CalendarInterval value={payload.new_time} /></dd></div>}
      {original?.recurring_instance && <div><dt>적용 범위</dt><dd>선택한 반복 일정 한 회차</dd></div>}
    </dl>
    <p className="review-note">승인하면 기본 Google 캘린더에 반영합니다.</p>
  </div>
}
