import { useCallback, useEffect, useRef, useState } from "react"
import { apiFetch } from "../api.js"

// 일정 탭 — 본인 주 캘린더 기간 조회(/api/calendar/events)와 월간 달력 순수 계산.
// 일정 시각은 서버가 돌려준 Google 원문(offset dateTime·종일 date)을 그대로 쓰고
// 날짜 칸·시간 표기는 브라우저 현지 시간대로 정한다.

export const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"]
const MAX_SPAN_DAYS = 62 // 서버 조회 한도(62일)와 맞춘 안전 상한

// 로컬 날짜 키(YYYY-MM-DD). 달력 칸·그룹화의 기준이다.
export function dateKey(date) {
  const month = String(date.getMonth() + 1).padStart(2, "0")
  const day = String(date.getDate()).padStart(2, "0")
  return `${date.getFullYear()}-${month}-${day}`
}

export function monthKey(year, month) {
  return `${year}-${String(month).padStart(2, "0")}`
}

export function parseMonthKey(key) {
  const [year, month] = key.split("-").map(Number)
  return { year, month }
}

// 월간 격자: 해당 달 1일이 속한 주의 일요일부터 42칸(6주). inMonth로 소속 달을 구분한다.
export function monthGrid(year, month) {
  const first = new Date(year, month - 1, 1)
  const cells = []
  for (let index = 0; index < 42; index += 1) {
    const day = new Date(first.getFullYear(), first.getMonth(), 1 - first.getDay() + index)
    cells.push({ key: dateKey(day), day: day.getDate(), inMonth: day.getMonth() === month - 1 })
  }
  return cells
}

// 조회 범위: 격자 앞뒤로 하루씩 여유를 둔다(시간대 경계의 종일 일정까지 담는다).
export function monthWindow(year, month) {
  const cells = monthGrid(year, month)
  const first = cells[0].key.split("-").map(Number)
  const last = cells[cells.length - 1].key.split("-").map(Number)
  const start = new Date(first[0], first[1] - 1, first[2] - 1)
  const end = new Date(last[0], last[1] - 1, last[2] + 2)
  return { start: start.toISOString(), end: end.toISOString() }
}

// 날짜 키를 n일 움직인다(종일 구간 계산용).
export function shiftDateKey(key, days) {
  const [year, month, day] = key.split("-").map(Number)
  return dateKey(new Date(year, month - 1, day + days))
}

// 이벤트가 덮는 로컬 날짜 키들. 종일은 end가 배타적(당일 하루면 end가 다음날),
// 시간 일정은 그 날 하루와 겹치는 날 전부(자정 넘김 포함)를 센다.
export function eventDateKeys(event) {
  if (event.all_day) {
    const keys = []
    for (let key = event.start; key <= shiftDateKey(event.end, -1) && keys.length < MAX_SPAN_DAYS;
      key = shiftDateKey(key, 1)) keys.push(key)
    return keys
  }
  const start = new Date(event.start)
  const end = new Date(event.end)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return []
  const keys = []
  const cursor = new Date(start.getFullYear(), start.getMonth(), start.getDate())
  const last = new Date(end.getFullYear(), end.getMonth(), end.getDate())
  while (cursor <= last && keys.length < MAX_SPAN_DAYS) {
    const dayEnd = new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate() + 1)
    if (start < dayEnd && end > cursor) keys.push(dateKey(cursor))
    cursor.setDate(cursor.getDate() + 1)
  }
  return keys
}

// 일정을 날짜별로 묶고 정렬한다(종일 먼저, 그다음 시작 시각). 순수 함수 — 테스트 대상.
export function groupEventsByDay(events) {
  const groups = new Map()
  for (const event of events) {
    for (const key of eventDateKeys(event)) {
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push(event)
    }
  }
  for (const list of groups.values()) {
    list.sort((a, b) => {
      if (a.all_day !== b.all_day) return a.all_day ? -1 : 1
      if (a.all_day) return a.start.localeCompare(b.start)
      return new Date(a.start) - new Date(b.start)
    })
  }
  return groups
}

function pad2(value) {
  return String(value).padStart(2, "0")
}

function shortDate(key) {
  const [, month, day] = key.split("-").map(Number)
  return `${month}/${day}`
}

// 목록에 쓰는 시각 표기. 종일 하루면 "종일", 여러 날 종일이면 "11/18~11/20",
// 시간 일정은 "10:00~11:30", 자정을 넘으면 날짜를 함께 적는다.
export function formatEventWhen(event) {
  if (!event.all_day) {
    const start = new Date(event.start)
    const end = new Date(event.end)
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return ""
    const from = `${pad2(start.getHours())}:${pad2(start.getMinutes())}`
    const to = `${pad2(end.getHours())}:${pad2(end.getMinutes())}`
    if (dateKey(start) === dateKey(end)) return `${from}~${to}`
    return `${shortDate(dateKey(start))} ${from}~${shortDate(dateKey(end))} ${to}`
  }
  const lastDay = shiftDateKey(event.end, -1)
  return event.start === lastDay ? "종일" : `${shortDate(event.start)}~${shortDate(lastDay)}`
}

// 격자 칩에 쓰는 짧은 시작 시각("10:00"). 종일은 null.
export function eventChipTime(event) {
  if (event.all_day) return null
  const start = new Date(event.start)
  return Number.isNaN(start.getTime()) ? null : `${pad2(start.getHours())}:${pad2(start.getMinutes())}`
}

// 날짜 키를 "11월 18일 수요일"로 바꾼다.
export function dayLabel(key) {
  const [year, month, day] = key.split("-").map(Number)
  const date = new Date(year, month - 1, day)
  return `${month}월 ${day}일 ${WEEKDAYS[date.getDay()]}요일`
}

// 월 단위 조회. 같은 달은 캐시를 먼저 보여 주고 뒤에서 다시 받는다(수동 새로고침은 캐시를 비운다).
export function useCalendarEvents(token, year, month, enabled = true) {
  const [state, setState] = useState({ events: [], loading: true, error: "" })
  const cache = useRef(new Map())
  const [reload, setReload] = useState(0)

  useEffect(() => {
    if (!enabled || !token) {
      setState({ events: [], loading: false, error: "" })
      return undefined
    }
    const controller = new AbortController()
    const key = monthKey(year, month)
    const cached = cache.current.get(key)
    if (cached) setState({ events: cached, loading: true, error: "" })
    else setState((previous) => ({ ...previous, loading: true, error: "" }))
    const window = monthWindow(year, month)
    apiFetch(`/calendar/events?start=${encodeURIComponent(window.start)}&end=${encodeURIComponent(window.end)}`,
      { token, signal: controller.signal }).then((response) => {
      if (controller.signal.aborted) return
      cache.current.set(key, response.events ?? [])
      setState({ events: response.events ?? [], loading: false, error: "" })
    }).catch((error) => {
      if (error.name === "AbortError") return
      setState({ events: cached ?? [], loading: false, error: error.message })
    })
    return () => controller.abort()
  }, [token, year, month, reload, enabled])

  const retry = useCallback(() => {
    cache.current.clear()
    setReload((value) => value + 1)
  }, [])
  return { ...state, retry }
}
