import { useEffect, useState } from 'react'
import { Alert, Card, List, Typography } from 'antd'
import type { SchedulePreviewInput, ScheduleType } from '../api/types'
import { previewSchedule } from '../api/endpoints'
import { ApiError } from '../api/client'
import { dayjs } from '../utils/time'

interface Props {
  enabled: boolean
  utcOffset: string
  values: {
    type: ScheduleType
    cron?: string | null
    runAt?: dayjs.Dayjs | null
    intervalSeconds?: number | null
  }
}

export function toPreviewRunAt(value: dayjs.Dayjs | null | undefined, offset: string): string | null {
  if (!value) return null
  return new Date(`${value.format('YYYY-MM-DDTHH:mm:ss')}${offset}`).toISOString()
}

export function SchedulePreview({ enabled, utcOffset, values }: Props) {
  const [occurrences, setOccurrences] = useState<{ utc: string; local: string }[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const { type, cron, runAt, intervalSeconds } = values

  useEffect(() => {
    if (!enabled || type === 'none') {
      setOccurrences([])
      setError(null)
      return
    }
    let cancelled = false
    const timer = setTimeout(async () => {
      setLoading(true)
      const payload: SchedulePreviewInput = {
        type,
        cron: type === 'cron' ? cron ?? null : null,
        run_at: type === 'once' ? toPreviewRunAt(runAt, utcOffset) : null,
        interval_seconds: type === 'interval' ? intervalSeconds ?? null : null,
        count: 5,
      }
      try {
        const response = await previewSchedule(payload)
        if (!cancelled) {
          setOccurrences(response.occurrences)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) {
          setOccurrences([])
          setError(err instanceof ApiError ? err.message : 'Preview failed')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }, 400)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [enabled, type, cron, runAt, intervalSeconds, utcOffset])

  if (!enabled || type === 'none') {
    return (
      <Alert
        type="info"
        showIcon
        message="Manual runs only; no automatic schedule"
        style={{ marginTop: 8 }}
      />
    )
  }

  return (
    <Card size="small" title={`Upcoming run times (UTC${utcOffset})`} style={{ marginTop: 8 }} loading={loading}>
      {error ? <Alert type="warning" showIcon message={error} /> : null}
      {occurrences.length === 0 && !error ? (
        <Typography.Text type="secondary">No run times to preview</Typography.Text>
      ) : (
        <List
          size="small"
          dataSource={occurrences}
          renderItem={(item) => (
            <List.Item>
              <Typography.Text>{item.local}</Typography.Text>
              <Typography.Text type="secondary">{item.utc}</Typography.Text>
            </List.Item>
          )}
        />
      )}
    </Card>
  )
}
