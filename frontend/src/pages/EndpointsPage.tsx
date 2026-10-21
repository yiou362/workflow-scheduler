import { useState } from 'react'
import { App, Button, Space, Table, Tag, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import type { Endpoint } from '../api/types'
import {
  deleteEndpoint,
  disableEndpoint,
  enableEndpoint,
  setDefaultEndpoint,
  testEndpoint,
} from '../api/endpoints'
import { useEndpoints } from '../hooks/useEndpoints'
import { ApiError } from '../api/client'
import { ErrorState } from '../components/ErrorState'
import { TimeText } from '../components/TimeText'

export default function EndpointsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { message, modal } = App.useApp()
  const { data, error, isLoading } = useEndpoints()
  const [testing, setTesting] = useState<string | null>(null)

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['endpoints'] })
    queryClient.invalidateQueries({ queryKey: ['dashboard'] })
  }

  const defaultMutation = useMutation({
    mutationFn: setDefaultEndpoint,
    onSuccess: () => {
      message.success('Default endpoint updated')
      invalidate()
    },
    onError: (err) => message.error(err instanceof ApiError ? err.message : 'Operation failed'),
  })

  const toggleMutation = useMutation({
    mutationFn: async (endpoint: Endpoint) =>
      endpoint.enabled ? disableEndpoint(endpoint.id) : enableEndpoint(endpoint.id),
    onSuccess: () => {
      message.success('Enabled state updated')
      invalidate()
    },
    onError: (err) => message.error(err instanceof ApiError ? err.message : 'Operation failed'),
  })

  const removeMutation = useMutation({
    mutationFn: deleteEndpoint,
    onSuccess: () => {
      message.success('Endpoint deleted')
      invalidate()
    },
    onError: (err) => message.error(err instanceof ApiError ? err.message : 'Delete failed'),
  })

  const runTest = async (endpoint: Endpoint) => {
    setTesting(endpoint.id)
    try {
      const result = await testEndpoint({ endpoint_id: endpoint.id, auth_type: endpoint.auth_type })
      if (result.result === 'success') message.success(result.message)
      else message.warning(result.message)
      invalidate()
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : 'Connection test failed')
    } finally {
      setTesting(null)
    }
  }

  const columns: ColumnsType<Endpoint> = [
    {
      title: 'Name',
      dataIndex: 'name',
      render: (value: string, record) => <a onClick={() => navigate(`/endpoints/${record.id}`)}>{value}</a>,
    },
    { title: 'Base URL', dataIndex: 'base_url', ellipsis: true },
    {
      title: 'Auth',
      dataIndex: 'auth_type',
      render: (value: string) => <Tag>{value === 'basic' ? 'Basic' : 'None'}</Tag>,
    },
    {
      title: 'Default',
      dataIndex: 'is_default',
      render: (value: boolean) => (value ? <Tag color="gold">Default</Tag> : '—'),
    },
    {
      title: 'Enabled',
      dataIndex: 'enabled',
      render: (value: boolean) => <Tag color={value ? 'green' : 'default'}>{value ? 'Enabled' : 'Disabled'}</Tag>,
    },
    { title: 'Tasks', dataIndex: 'task_count', width: 90 },
    {
      title: 'Last test',
      dataIndex: 'last_test_result',
      render: (value: string | null, record) =>
        value ? (
          <Tooltip title={record.last_test_message ?? ''}>
            <span>
              <Tag color={value === 'success' ? 'green' : 'red'}>{value}</Tag>
              <TimeText value={record.last_test_at} />
            </span>
          </Tooltip>
        ) : (
          'Not tested'
        ),
    },
    {
      title: 'Actions',
      width: 340,
      render: (_, record) => (
        <Space wrap>
          <Button size="small" onClick={() => navigate(`/endpoints/${record.id}/edit`)}>
            Edit
          </Button>
          <Button size="small" loading={testing === record.id} onClick={() => runTest(record)}>
            Test connection
          </Button>
          {!record.is_default ? (
            <Button size="small" onClick={() => defaultMutation.mutate(record.id)}>
              Set as default
            </Button>
          ) : null}
          <Button size="small" onClick={() => toggleMutation.mutate(record)}>
            {record.enabled ? 'Disable' : 'Enable'}
          </Button>
          <Button
            size="small"
            danger
            onClick={() =>
              modal.confirm({
                title: `Delete endpoint "${record.name}"?`,
                content:
                  'An endpoint cannot be deleted while it is the default, referenced by a task, or used by an active run.',
                okText: 'Delete',
                okButtonProps: { danger: true },
                onOk: () => removeMutation.mutateAsync(record.id),
              })
            }
          >
            Delete
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h3 style={{ margin: 0 }}>Endpoints</h3>
        <Button type="primary" onClick={() => navigate('/endpoints/new')}>
          New endpoint
        </Button>
      </div>
      <ErrorState error={error} />
      <Table<Endpoint>
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={data?.items ?? []}
        pagination={false}
      />
    </div>
  )
}
