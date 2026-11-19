import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { useAuth } from "../useAuth"
import {
  WEEKDAYS, dateKey, dayLabel, eventChipTime, formatEventWhen, groupEventsByDay, monthGrid, monthKey,
  parseMonthKey, useCalendarEvents,
} from "./useCalendarEvents.js"
import "./calendar.css"

// 일정 탭: 본인 주 캘린더를 월간 격자 + 선택한 날짜의 일정 목록으로 보여 준다(읽기 전용).
// 일정 등록은 업무 도우미 대화에서 승인해 Google에 등록하는 기존 경로를 쓴다.
const GRID_CHIPS = 2 // 칸마다 보여 주는 일정 칩 수. 나머지는 +N으로 건너뛴다.

export default function CalendarPage() {
  const { state, refreshMe } = useAuth()
  const token = state.accessToken
  const today = dateKey(new Date())
  const [view, setView] = useState(() => monthKey(new Date().getFullYear(), new Date().getMonth() + 1))
  const [direction, setDirection] = useState("next")
  const [selected, setSelected] = useState(today)
  const { year, month } = parseMonthKey(view)
  const connected = state.me?.calendar?.connected === true
  const events = useCalendarEvents(token, year, month, connected)

  // 다른 화면에서 캘린더를 막 연결했을 수 있으니 입장할 때 연결 상태만 새로 확인한다.
  useEffect(() => {
    if (!token) return undefined
    const controller = new AbortController()
    refreshMe(token, controller.signal).catch(() => {})
    return () => controller.abort()
  }, [token, refreshMe])

  function moveMonth(delta) {
    setDirection(delta > 0 ? "next" : "prev")
    const moved = new Date(year, month - 1 + delta, 1)
    applyMonth(moved.getFullYear(), moved.getMonth() + 1)
  }

  function goToday() {
    setDirection(view <= today.slice(0, 7) ? "next" : "prev")
    const now = new Date()
    applyMonth(now.getFullYear(), now.getMonth() + 1, today)
  }

  function applyMonth(nextYear, nextMonth, preferredKey) {
    setView(monthKey(nextYear, nextMonth))
    const keys = monthGrid(nextYear, nextMonth).filter((cell) => cell.inMonth).map((cell) => cell.key)
    setSelected(keys.includes(preferredKey ?? today) ? (preferredKey ?? today) : keys[0])
  }

  const cells = useMemo(() => monthGrid(year, month), [year, month])
  const groups = useMemo(() => groupEventsByDay(events.events), [events.events])
  const selectedEvents = groups.get(selected) ?? []

  if (state.me == null) {
    return <div className="cal-workspace"><p className="cal-hint" role="status">연동 상태를 확인하는 중입니다…</p></div>
  }
  if (!connected) {
    return <div className="cal-workspace">
      <div className="page-head">
        <div>
          <h1 className="page-title">일정</h1>
          <p className="page-sub">내 Google 캘린더 일정을 월간 달력으로 확인합니다.</p>
        </div>
      </div>
      <div className="cal-connect">
        <h2 className="section-title">Google 캘린더가 연결되지 않았습니다</h2>
        <p className="cal-connect-note">
          설정의 연동하기에서 Google 캘린더를 연결하면 내 주 캘린더 일정을 이 탭에서 확인할 수 있습니다.
          일정 등록은 업무 도우미 대화에서 승인해 진행합니다.
        </p>
        <Link className="btn blue" to="/settings">설정으로 이동</Link>
      </div>
    </div>
  }
  return <div className="cal-workspace">
    <div className="page-head">
      <div>
        <h1 className="page-title">일정</h1>
        <p className="page-sub">내 Google 캘린더 일정을 월간 달력으로 확인합니다. 등록은 업무 도우미 대화에서 승인해 진행합니다.</p>
      </div>
      <button type="button" className="btn" onClick={events.retry} disabled={events.loading}>새로고침</button>
    </div>
    {events.error && (
      <div className="cal-error" role="alert">
        <span>일정을 불러오지 못했습니다. {events.error}</span>
        <span className="cal-error-actions">
          <button type="button" className="btn" onClick={events.retry}>다시 시도</button>
          <Link className="cal-link" to="/settings">연결 설정</Link>
        </span>
      </div>
    )}
    <div className="cal-layout">
      <section className="cal-panel" aria-label="월간 달력">
        <div className="cal-head">
          <div className="cal-month">
            <button type="button" className="cal-nav" aria-label="지난 달" onClick={() => moveMonth(-1)}>‹</button>
            <strong className="cal-month-title">{year}년 {month}월</strong>
            <button type="button" className="cal-nav" aria-label="다음 달" onClick={() => moveMonth(1)}>›</button>
          </div>
          <button type="button" className="btn" onClick={goToday}>오늘</button>
        </div>
        <div className="cal-weekdays" aria-hidden="true">
          {WEEKDAYS.map((label) => <span key={label}>{label}</span>)}
        </div>
        {events.loading && !events.events.length ? (
          <div className="cal-grid" aria-label="불러오는 중">
            {Array.from({ length: 42 }, (_, index) => <div key={index} className="cal-cell cal-skeleton" />)}
          </div>
        ) : (
          <div key={view} className={`cal-grid cal-slide-${direction}`}>
            {cells.map((cell, index) => {
              const dayEvents = groups.get(cell.key) ?? []
              const visible = dayEvents.slice(0, GRID_CHIPS)
              const hidden = dayEvents.length - visible.length
              const classes = ["cal-cell"]
              if (!cell.inMonth) classes.push("cal-out")
              if (cell.key === today) classes.push("cal-today")
              return (
                <button key={cell.key} type="button" className={classes.join(" ")} aria-pressed={selected === cell.key}
                  onClick={() => setSelected(cell.key)}
                  style={{ animationDelay: `${Math.min(index * 7, 190)}ms` }}>
                  <span className="cal-daynum">{cell.day}</span>
                  {dayEvents.length > 0 && <span className="cal-count">{dayEvents.length}</span>}
                  {visible.map((event) => (
                    <span key={event.id} className={event.all_day ? "cal-chip cal-chip-allday" : "cal-chip"}>
                      {!event.all_day && <b>{eventChipTime(event)}</b>}{event.summary || "제목 없음"}
                    </span>
                  ))}
                  {hidden > 0 && <span className="cal-more">+{hidden}</span>}
                </button>
              )
            })}
          </div>
        )}
      </section>
      <aside className="cal-side" aria-label="선택한 날짜의 일정">
        <div className="cal-side-head">
          <h2 className="cal-side-title">{dayLabel(selected)}</h2>
          {selectedEvents.length > 0 && <span className="cal-side-count">{selectedEvents.length}건</span>}
        </div>
        {events.loading && selectedEvents.length === 0 && <p className="cal-hint" role="status">일정을 불러오는 중입니다…</p>}
        {!events.loading && !events.error && selectedEvents.length === 0 &&
          <p className="cal-hint">이 날짜에 등록된 일정이 없습니다.</p>}
        <ul className="cal-list">
          {selectedEvents.map((event, index) => (
            <li key={event.id} className="cal-item" style={{ animationDelay: `${Math.min(index * 45, 320)}ms` }}>
              <span className="cal-when">{formatEventWhen(event)}</span>
              <span className="cal-summary">{event.summary || "제목 없음"}</span>
            </li>
          ))}
        </ul>
      </aside>
    </div>
  </div>
}
