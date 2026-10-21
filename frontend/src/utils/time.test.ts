import { describe, expect, it } from 'vitest'
import { dayjs, formatDuration, formatTime, offsetLabel, wallClockToIso } from './time'

describe('time utils', () => {
  it('formats UTC instants in UTC+08:00', () => {
    expect(formatTime('2026-10-19T01:00:00.000Z')).toBe('2026-10-19 09:00:00')
  })

  it('renders empty values as a dash', () => {
    expect(formatTime(null)).toBe('—')
  })

  it('formats durations', () => {
    expect(formatDuration(65_000)).toBe('1m 5s')
    expect(formatDuration(3_725_000)).toBe('1h 2m 5s')
    expect(formatDuration(null)).toBe('—')
  })

  it('labels the fixed offset', () => {
    expect(offsetLabel('+08:00')).toBe('UTC+08:00')
  })

  it('interprets picked wall clock as UTC+08:00', () => {
    const value = dayjs('2026-10-19T09:00:00')
    expect(wallClockToIso(value, value, '+08:00')).toBe('2026-10-19T01:00:00.000Z')
  })
})
