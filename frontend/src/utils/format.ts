import type { RunStatus, ScheduleType, TraceIntegrity, TriggerSource } from '../api/types'

export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  queued: 'Queued',
  preparing: 'Preparing',
  submitting: 'Submitting',
  running: 'Running',
  waiting: 'Waiting for permission',
  completed: 'Completed',
  failed: 'Failed',
  cancelling: 'Cancelling',
  cancelled: 'Cancelled',
  timeout: 'Timed out',
  skipped: 'Skipped',
  unknown: 'Unknown',
}

export const RUN_STATUS_COLORS: Record<RunStatus, string> = {
  queued: 'default',
  preparing: 'blue',
  submitting: 'blue',
  running: 'blue',
  waiting: 'orange',
  completed: 'green',
  failed: 'red',
  cancelling: 'purple',
  cancelled: 'default',
  timeout: 'red',
  skipped: 'default',
  unknown: 'red',
}

export const TASK_STATUS_LABELS: Record<string, string> = {
  enabled: 'Enabled',
  disabled: 'Disabled',
  archived: 'Archived',
}

export const TRIGGER_LABELS: Record<TriggerSource, string> = {
  scheduled: 'Scheduled',
  manual: 'Manual',
  rerun: 'Rerun',
  recovery: 'Recovery',
}

export const SCHEDULE_TYPE_LABELS: Record<ScheduleType, string> = {
  none: 'No automatic schedule',
  cron: 'Cron',
  once: 'Once',
  interval: 'Fixed interval',
}

export const INTEGRITY_LABELS: Record<TraceIntegrity, string> = {
  complete: 'Trace complete',
  gap: 'Trace has gaps, backfilled from the final message',
  incomplete: 'Trace incomplete, for reference only',
  none: 'No trace available',
}

export const INTEGRITY_COLORS: Record<TraceIntegrity, string> = {
  complete: 'green',
  gap: 'orange',
  incomplete: 'red',
  none: 'default',
}

export function prettyJson(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2)
    } catch {
      return value
    }
  }
  return JSON.stringify(value, null, 2)
}

export function shortId(id: string | null | undefined): string {
  if (!id) return '—'
  return id.length > 16 ? `${id.slice(0, 12)}…` : id
}
