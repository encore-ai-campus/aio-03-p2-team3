import assert from "node:assert/strict"
import test from "node:test"

import {
  WEEKDAYS, dayLabel, eventChipTime, eventDateKeys, formatEventWhen, groupEventsByDay, monthGrid,
  monthKey, monthWindow, parseMonthKey, shiftDateKey,
} from "./useCalendarEvents.js"

function weekdayOf(key) {
  const [year, month, day] = key.split("-").map(Number)
  return new Date(year, month - 1, day).getDay()
}

test("monthGrid는 일요일 시작 42칸에 달 소속을 표시한다", () => {
  const cells = monthGrid(2026, 11)
  assert.equal(cells.length, 42)
  assert.equal(weekdayOf(cells[0].key), 0) // 첫 칸은 일요일
  assert.ok(cells.some((cell) => cell.key === "2026-11-01" && cell.inMonth)) // 그 달 1일 포함
  assert.equal(cells.filter((cell) => cell.inMonth).length, 30) // 11월은 30일
  for (let index = 1; index < cells.length; index += 1) { // 날짜가 하루씩 이어진다
    assert.equal(shiftDateKey(cells[index - 1].key, 1), cells[index].key)
  }
})

test("shiftDateKey는 달 경계를 넘어 이동한다", () => {
  assert.equal(shiftDateKey("2026-11-01", -1), "2026-10-31")
  assert.equal(shiftDateKey("2026-11-30", 1), "2026-12-01")
})

test("eventDateKeys는 시간 일정이 닿는 날만 센다(자정 넘김·end 배타)", () => {
  assert.deepEqual(
    eventDateKeys({ start: "2026-11-18T10:00:00", end: "2026-11-18T11:00:00", all_day: false }),
    ["2026-11-18"])
  assert.deepEqual(
    eventDateKeys({ start: "2026-11-18T23:00:00", end: "2026-11-19T01:00:00", all_day: false }),
    ["2026-11-18", "2026-11-19"])
  assert.deepEqual( // 끝이 정확히 자정이면 다음 날은 세지 않는다
    eventDateKeys({ start: "2026-11-18T23:00:00", end: "2026-11-19T00:00:00", all_day: false }),
    ["2026-11-18"])
  assert.deepEqual(eventDateKeys({ start: "not-a-date", end: "2026-11-19", all_day: false }), [])
})

test("eventDateKeys는 종일 일정을 end 전날까지 센다", () => {
  assert.deepEqual(
    eventDateKeys({ start: "2026-11-18", end: "2026-11-19", all_day: true }), ["2026-11-18"])
  assert.deepEqual(
    eventDateKeys({ start: "2026-11-18", end: "2026-11-21", all_day: true }),
    ["2026-11-18", "2026-11-19", "2026-11-20"])
})

test("groupEventsByDay는 날짜별로 묶고 종일 먼저·시작 순으로 정렬한다", () => {
  const groups = groupEventsByDay([
    { id: "b", summary: "오후 회의", start: "2026-11-18T14:00:00", end: "2026-11-18T15:00:00", all_day: false },
    { id: "a", summary: "오전 회의", start: "2026-11-18T09:00:00", end: "2026-11-18T10:00:00", all_day: false },
    { id: "c", summary: "휴가", start: "2026-11-18", end: "2026-11-19", all_day: true },
    { id: "d", summary: "다른 날", start: "2026-11-20T10:00:00", end: "2026-11-20T11:00:00", all_day: false },
  ])
  assert.deepEqual(groups.get("2026-11-18").map((event) => event.id), ["c", "a", "b"])
  assert.deepEqual(groups.get("2026-11-20").map((event) => event.id), ["d"])
  assert.equal(groups.get("2026-11-19"), undefined)
})

test("formatEventWhen은 종일·당일·자정 넘김을 각각 표기한다", () => {
  assert.equal(
    formatEventWhen({ start: "2026-11-18", end: "2026-11-19", all_day: true }), "종일")
  assert.equal(
    formatEventWhen({ start: "2026-11-18", end: "2026-11-21", all_day: true }), "11/18~11/20")
  assert.equal(
    formatEventWhen({ start: "2026-11-18T10:00:00", end: "2026-11-18T11:30:00", all_day: false }), "10:00~11:30")
  assert.equal(
    formatEventWhen({ start: "2026-11-18T23:00:00", end: "2026-11-19T01:00:00", all_day: false }),
    "11/18 23:00~11/19 01:00")
})

test("eventChipTime과 dayLabel을 만든다", () => {
  assert.equal(eventChipTime({ start: "2026-11-18T10:05:00", end: "2026-11-18T11:00:00", all_day: false }), "10:05")
  assert.equal(eventChipTime({ start: "2026-11-18", end: "2026-11-19", all_day: true }), null)
  const [year, month, day] = "2026-11-18".split("-").map(Number)
  assert.equal(dayLabel("2026-11-18"),
    `11월 18일 ${WEEKDAYS[new Date(year, month - 1, day).getDay()]}요일`)
})

test("monthWindow는 격자보다 하루씩 넓고 조회 한도(62일) 안에 든다", () => {
  const cells = monthGrid(2026, 11)
  const first = cells[0].key.split("-").map(Number)
  const last = cells[cells.length - 1].key.split("-").map(Number)
  const window = monthWindow(2026, 11)
  assert.equal(new Date(window.start).getTime(), new Date(first[0], first[1] - 1, first[2] - 1).getTime())
  assert.equal(new Date(window.end).getTime(), new Date(last[0], last[1] - 1, last[2] + 2).getTime())
  const days = (new Date(window.end) - new Date(window.start)) / 86400000
  assert.ok(days > 42 && days <= 62)
  assert.match(window.start, /Z$/)
})

test("monthKey·parseMonthKey는 서로 되돌린다", () => {
  assert.equal(monthKey(2026, 11), "2026-11")
  assert.deepEqual(parseMonthKey("2026-11"), { year: 2026, month: 11 })
})
