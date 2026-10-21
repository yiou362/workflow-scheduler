import { useState } from 'react'
import { Card, DatePicker, Input, Select, Space, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import type { RunListItem } from '../api/types'
import { useRuns } from '../hooks/useRuns'
import { useTasks } from '../hooks/useTasks'
import { useEndpoints } from '../hooks/useEndpoints'
import { ErrorState } from '../components/ErrorState'
import { StatusTag } from '../components/StatusTag'
import { TimeText } from '../components/TimeText'
import { TRIGGER_LABELS } from '../utils/format'
import { formatDuration } from '../utils/time'

export default function RunsPage() {
  const navigate = useNavigate()
  const [filters, setFilters] = useState<{
    task_id?: string
    endpoint_id?: string
    status?: string
    source?: string
    from?: string
    to?: string
    model?: string
    page: number
  }>({ page: 1 })

  const { data, error, isLoading } = useRuns({ ...filters, page_size: 50 })
  const tasks = useTasks({ page_size: 200 })
  const endpoints = useEndpoints()

  const columns: ColumnsType<RunListItem> = [
    {
      title: 'Task',
      dataIndex: 'task_name',
      ellipsis: true,
      render: (value: string, record) => <a onClick={() => navigate(`/runs/${record.id}`)}>{value}</a>,
    },
    { title: 'Status', dataIndex: 'status', render: (value: string) => <StatusTag status={value} /> },
    { title: 'Endpoint', dataIndex: 'endpoint_name', ellipsis: true },
    {
      title: 'Source',
      dataIndex: 'trigger_source',
      render: (value: keyof typeof TRIGGER_LABELS) => TRIGGER_LABELS[value] ?? value,
    },
    { title: 'Started at', dataIndex: 'started_at', render: (value: string) => <TimeText value={value} /> },
    { title: 'Finished at', dataIndex: 'finished_at', render: (value: string) => <TimeText value={value} /> },
    {
      title: 'Duration',
      dataIndex: 'duration_ms',
      render: (value: number | null) => formatDuration(value),
    },
    {
      title: 'Trace integrity',
      dataIndex: 'trace_integrity',
      render: (value: string | null) => value ?? '—',
    },
  ]

  return (
    <div>
      <h3 style={{ marginTop: 0 }}>Runs</h3>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="Task"
            style={{ width: 200 }}
            value={filters.task_id}
            onChange={(value) => setFilters((prev) => ({ ...prev, task_id: value, page: 1 }))}
            options={(tasks.data?.items ?? []).map((item) => ({ value: item.id, label: item.name }))}
          />
          <Select
            allowClear
            placeholder="Endpoint"
            style={{ width: 170 }}
            value={filters.endpoint_id}
            onChange={(value) => setFilters((prev) => ({ ...prev, endpoint_id: value, page: 1 }))}
            options={(endpoints.data?.items ?? []).map((item) => ({ value: item.id, label: item.name }))}
          />
          <Select
            allowClear
            placeholder="Status"
            style={{ width: 140 }}
            value={filters.status}
            onChange={(value) => setFilters((prev) => ({ ...prev, status: value, page: 1 }))}
            options={[
              'queued',
              'preparing',
              'submitting',
              'running',
              'waiting',
              'completed',
              'failed',
              'cancelling',
              'cancelled',
              'timeout',
              'skipped',
              'unknown',
            ].map((value) => ({ value, label: value }))}
          />
          <Select
            allowClear
            placeholder="Source"
            style={{ width: 140 }}
            value={filters.source}
            onChange={(value) => setFilters((prev) => ({ ...prev, source: value, page: 1 }))}
            options={[
              { value: 'scheduled', label: 'Scheduled' },
              { value: 'manual', label: 'Manual' },
              { value: 'rerun', label: 'Rerun' },
              { value: 'recovery', label: 'Recovery' },
            ]}
          />
          <DatePicker.RangePicker
            onChange={(_, text) =>
              setFilters((prev) => ({ ...prev, from: text[0] ?? undefined, to: text[1] ?? undefined, page: 1 }))
            }
          />
          <Input
            allowClear
            placeholder="Model"
            style={{ width: 180 }}
            value={filters.model}
            onChange={(event) => setFilters((prev) => ({ ...prev, model: event.target.value, page: 1 }))}
          />
        </Space>
      </Card>
      <ErrorState error={error} />
      <Table<RunListItem>
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={data?.items ?? []}
        onRow={(record) => ({ onClick: () => navigate(`/runs/${record.id}`) })}
        pagination={{
          current: filters.page,
          pageSize: 50,
          total: data?.total ?? 0,
          showSizeChanger: false,
          onChange: (page) => setFilters((prev) => ({ ...prev, page })),
        }}
      />
    </div>
  )
}
