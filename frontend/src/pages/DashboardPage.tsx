import { Card, Col, Row, Statistic, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import type { RunListItem } from '../api/types'
import { useDashboard } from '../hooks/useDashboard'
import { ErrorState } from '../components/ErrorState'
import { StatusTag } from '../components/StatusTag'
import { TimeText } from '../components/TimeText'
import { TRIGGER_LABELS } from '../utils/format'

const recentColumns: ColumnsType<RunListItem> = [
  { title: 'Task', dataIndex: 'task_name', ellipsis: true },
  { title: 'Endpoint', dataIndex: 'endpoint_name', ellipsis: true },
  { title: 'Status', dataIndex: 'status', render: (value: string) => <StatusTag status={value} /> },
  {
    title: 'Source',
    dataIndex: 'trigger_source',
    render: (value: keyof typeof TRIGGER_LABELS) => TRIGGER_LABELS[value] ?? value,
  },
  { title: 'Started at', dataIndex: 'started_at', render: (value: string) => <TimeText value={value} /> },
]

export default function DashboardPage() {
  const navigate = useNavigate()
  const { data, error, isLoading } = useDashboard()

  const failureColumns: ColumnsType<RunListItem> = [
    ...recentColumns.slice(0, 4),
    { title: 'Error type', dataIndex: 'error_type', render: (value: string) => value ?? '—' },
    { title: 'Started at', dataIndex: 'started_at', render: (value: string) => <TimeText value={value} /> },
  ]

  return (
    <div>
      <Typography.Title level={4} className="page-title">
        Dashboard
      </Typography.Title>
      <ErrorState error={error} />
      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}>
          <Card title="Endpoint">
            <Row gutter={16}>
              <Col span={8}>
                <Statistic title="Total" value={data?.endpoints.total ?? 0} loading={isLoading} />
              </Col>
              <Col span={8}>
                <Statistic title="Enabled" value={data?.endpoints.enabled ?? 0} loading={isLoading} />
              </Col>
              <Col span={8}>
                <Statistic title="Disabled" value={data?.endpoints.disabled ?? 0} loading={isLoading} />
              </Col>
            </Row>
            <Typography.Paragraph style={{ marginTop: 12, marginBottom: 0 }}>
              Default: {data?.endpoints.default?.name ?? 'not set'}
            </Typography.Paragraph>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card title="Task">
            <Row gutter={16}>
              <Col span={6}>
                <Statistic title="Total" value={data?.tasks.total ?? 0} loading={isLoading} />
              </Col>
              <Col span={6}>
                <Statistic title="Enabled" value={data?.tasks.enabled ?? 0} loading={isLoading} />
              </Col>
              <Col span={6}>
                <Statistic title="Disabled" value={data?.tasks.disabled ?? 0} loading={isLoading} />
              </Col>
              <Col span={6}>
                <Statistic title="Archived" value={data?.tasks.archived ?? 0} loading={isLoading} />
              </Col>
            </Row>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card title="Run">
            <Row gutter={16}>
              <Col span={8}>
                <Statistic title="Queued" value={data?.runs.queued ?? 0} loading={isLoading} />
              </Col>
              <Col span={8}>
                <Statistic title="Running" value={data?.runs.running ?? 0} loading={isLoading} />
              </Col>
              <Col span={8}>
                <Statistic title="Waiting" value={data?.runs.waiting ?? 0} loading={isLoading} />
              </Col>
            </Row>
            <Row gutter={16} style={{ marginTop: 12 }}>
              <Col span={12}>
                <Statistic title="Failed (last 30 days)" value={data?.runs.failed_30d ?? 0} loading={isLoading} />
              </Col>
              <Col span={12}>
                <Statistic title="Completed (last 30 days)" value={data?.runs.completed_30d ?? 0} loading={isLoading} />
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>

      <Card title="Upcoming runs" style={{ marginTop: 16 }} loading={isLoading}>
        <Table
          rowKey="task_id"
          size="small"
          pagination={false}
          dataSource={data?.upcoming ?? []}
          columns={[
            { title: 'Task', dataIndex: 'task_name' },
            {
              title: 'Next run',
              dataIndex: 'next_run_at',
              render: (value: string) => <TimeText value={value} showOffset />,
            },
            { title: 'Schedule', dataIndex: 'schedule_summary' },
            {
              title: '',
              render: (_, record) => (
                <a onClick={() => navigate(`/tasks/${record.task_id}`)}>View task</a>
              ),
            },
          ]}
          onRow={(record) => ({ onClick: () => navigate(`/tasks/${record.task_id}`) })}
        />
      </Card>

      <Card title="Recent runs" style={{ marginTop: 16 }} loading={isLoading}>
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          columns={recentColumns}
          dataSource={data?.recent_runs ?? []}
          onRow={(record) => ({ onClick: () => navigate(`/runs/${record.id}`) })}
        />
      </Card>

      <Card
        title={
          <span>
            Recent failures <Tag color="red">Failed / Timeout / Unknown</Tag>
          </span>
        }
        style={{ marginTop: 16 }}
        loading={isLoading}
      >
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          columns={failureColumns}
          dataSource={data?.recent_failures ?? []}
          onRow={(record) => ({ onClick: () => navigate(`/runs/${record.id}`) })}
        />
      </Card>
    </div>
  )
}
