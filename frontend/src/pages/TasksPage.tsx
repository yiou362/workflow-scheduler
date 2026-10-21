import { useState } from 'react'
import { App, Button, Card, Input, Select, Space, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { Task } from '../api/types'
import { runTaskNow } from '../api/endpoints'
import { useTasks } from '../hooks/useTasks'
import { useEndpoints } from '../hooks/useEndpoints'
import { ApiError } from '../api/client'
import { ErrorState } from '../components/ErrorState'
import { StatusTag, TaskStatusTag } from '../components/StatusTag'
import { TimeText } from '../components/TimeText'

export default function TasksPage() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [filters, setFilters] = useState<{
    status?: string
    endpoint_id?: string
    schedule_type?: string
    last_status?: string
    tag?: string
    page: number
  }>({ page: 1 })
  const { data, error, isLoading } = useTasks({ ...filters, page_size: 20 })
  const endpoints = useEndpoints()

  const runMutation = useMutation({
    mutationFn: runTaskNow,
    onSuccess: (response) => {
      message.success(response.message)
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      navigate(`/runs/${response.run.id}`)
    },
    onError: (err) => message.error(err instanceof ApiError ? err.message : 'Execution failed'),
  })

  const columns: ColumnsType<Task> = [
    {
      title: 'Name',
      dataIndex: 'name',
      render: (value: string, record) => <a onClick={() => navigate(`/tasks/${record.id}`)}>{value}</a>,
    },
    { title: 'Endpoint', dataIndex: 'endpoint_name', render: (value: string | null) => value ?? '—' },
    { title: 'Working directory', dataIndex: 'working_directory', ellipsis: true },
    { title: 'Model', dataIndex: 'model_id', ellipsis: true },
    { title: 'Schedule', dataIndex: 'schedule_summary' },
    {
      title: 'Status',
      dataIndex: 'status',
      render: (value: string) => <TaskStatusTag status={value} />,
    },
    {
      title: 'Next run',
      dataIndex: 'next_run_at',
      render: (value: string | null) => <TimeText value={value} showOffset />,
    },
    {
      title: 'Last run',
      dataIndex: 'last_run',
      render: (value: Task['last_run']) =>
        value ? (
          <Space size="small">
            <StatusTag status={value.status} />
            <TimeText value={value.started_at ?? value.created_at} />
          </Space>
        ) : (
          '—'
        ),
    },
    {
      title: 'Actions',
      width: 230,
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => navigate(`/tasks/${record.id}/edit`)}>
            Edit
          </Button>
          <Button
            size="small"
            type="primary"
            disabled={record.status === 'archived'}
            loading={runMutation.isPending}
            onClick={() => runMutation.mutate(record.id)}
          >
            Run now
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h3 style={{ margin: 0 }}>Tasks</h3>
        <Button type="primary" onClick={() => navigate('/tasks/new')}>
          New task
        </Button>
      </div>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            allowClear
            placeholder="Status"
            style={{ width: 130 }}
            value={filters.status}
            onChange={(value) => setFilters((prev) => ({ ...prev, status: value, page: 1 }))}
            options={[
              { value: 'enabled', label: 'Enabled' },
              { value: 'disabled', label: 'Disabled' },
              { value: 'archived', label: 'Archived' },
            ]}
          />
          <Select
            allowClear
            placeholder="Endpoint"
            style={{ width: 180 }}
            value={filters.endpoint_id}
            onChange={(value) => setFilters((prev) => ({ ...prev, endpoint_id: value, page: 1 }))}
            options={(endpoints.data?.items ?? []).map((item) => ({ value: item.id, label: item.name }))}
          />
          <Select
            allowClear
            placeholder="Schedule type"
            style={{ width: 160 }}
            value={filters.schedule_type}
            onChange={(value) => setFilters((prev) => ({ ...prev, schedule_type: value, page: 1 }))}
            options={[
              { value: 'none', label: 'No automatic schedule' },
              { value: 'cron', label: 'Cron' },
              { value: 'once', label: 'Once' },
              { value: 'interval', label: 'Fixed interval' },
            ]}
          />
          <Select
            allowClear
            placeholder="Last run status"
            style={{ width: 170 }}
            value={filters.last_status}
            onChange={(value) => setFilters((prev) => ({ ...prev, last_status: value, page: 1 }))}
            options={['queued', 'running', 'completed', 'failed', 'skipped', 'unknown'].map((value) => ({
              value,
              label: value,
            }))}
          />
          <Input
            allowClear
            placeholder="Tag"
            style={{ width: 140 }}
            value={filters.tag}
            onChange={(event) => setFilters((prev) => ({ ...prev, tag: event.target.value, page: 1 }))}
          />
        </Space>
      </Card>
      <ErrorState error={error} />
      <Table<Task>
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={data?.items ?? []}
        pagination={{
          current: filters.page,
          pageSize: 20,
          total: data?.total ?? 0,
          onChange: (page) => setFilters((prev) => ({ ...prev, page })),
          showSizeChanger: false,
        }}
      />
    </div>
  )
}
