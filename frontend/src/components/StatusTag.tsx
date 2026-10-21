import { Tag } from 'antd'
import type { RunStatus } from '../api/types'
import { RUN_STATUS_COLORS, RUN_STATUS_LABELS, TASK_STATUS_LABELS } from '../utils/format'

export function StatusTag({ status }: { status: RunStatus | string | null }) {
  const key = (status ?? 'unknown') as RunStatus
  const label = RUN_STATUS_LABELS[key] ?? status ?? 'Unknown'
  const color = RUN_STATUS_COLORS[key] ?? 'default'
  return <Tag color={color}>{label}</Tag>
}

export function TaskStatusTag({ status }: { status: string }) {
  const color = status === 'enabled' ? 'green' : status === 'archived' ? 'default' : 'orange'
  return <Tag color={color}>{TASK_STATUS_LABELS[status] ?? status}</Tag>
}
