import dayjs, { type Dayjs } from 'dayjs'
import utc from 'dayjs/plugin/utc'
import 'dayjs/locale/en'

dayjs.extend(utc)
dayjs.locale('en')

export const DEFAULT_OFFSET = '+08:00'

export function formatTime(value: string | null | undefined, offset: string = DEFAULT_OFFSET): string {
  if (!value) return '—'
  return dayjs.utc(value).utcOffset(offset).format('YYYY-MM-DD HH:mm:ss')
}

export function formatDate(value: string | null | undefined, offset: string = DEFAULT_OFFSET): string {
  if (!value) return '—'
  return dayjs.utc(value).utcOffset(offset).format('YYYY-MM-DD')
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 0) return '—'
  const totalSeconds = Math.floor(ms / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`
  if (minutes > 0) return `${minutes}m ${seconds}s`
  return `${seconds}s`
}

export function offsetLabel(offset: string = DEFAULT_OFFSET): string {
  return `UTC${offset}`
}

/** Interpret the picked wall-clock date/time as the global offset, not the browser zone. */
export function wallClockToIso(date: Dayjs, time: Dayjs, offset: string = DEFAULT_OFFSET): string {
  const text = `${date.format('YYYY-MM-DD')}T${time.format('HH:mm:ss')}${offset}`
  return new Date(text).toISOString()
}

export function isoToWallClock(iso: string | null | undefined, offset: string = DEFAULT_OFFSET): { date: Dayjs; time: Dayjs } | null {
  if (!iso) return null
  const local = dayjs.utc(iso).utcOffset(offset)
  return { date: local, time: local }
}

export { dayjs }
