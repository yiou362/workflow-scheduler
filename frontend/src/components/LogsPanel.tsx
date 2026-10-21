import { Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { LogEntry } from '../api/types'
import { TimeText } from './TimeText'
import { prettyJson } from '../utils/format'

const columns: ColumnsType<LogEntry> = [
  {
    title: 'Time',
    dataIndex: 'at',
    width: 190,
    render: (value: string) => <TimeText value={value} />,
  },
  {
    title: 'Level',
    dataIndex: 'level',
    width: 80,
    render: (value: string) => (
      <Tag color={value === 'error' ? 'red' : value === 'warn' ? 'orange' : 'blue'}>{value}</Tag>
    ),
  },
  { title: 'Phase', dataIndex: 'phase', width: 160 },
  { title: 'Message', dataIndex: 'message', render: (value: string) => <Typography.Text>{value}</Typography.Text> },
  {
    title: 'Details',
    dataIndex: 'details',
    render: (value: Record<string, unknown> | null) =>
      value ? <pre style={{ margin: 0, maxWidth: 320, whiteSpace: 'pre-wrap' }}>{prettyJson(value)}</pre> : '—',
  },
]

export function LogsPanel({ logs }: { logs: LogEntry[] }) {
  return (
    <Table<LogEntry>
      rowKey="id"
      size="small"
      columns={columns}
      dataSource={logs}
      pagination={false}
      locale={{ emptyText: 'No log entries' }}
    />
  )
}
