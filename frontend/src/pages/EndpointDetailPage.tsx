import { useState } from 'react'
import { App, Button, Card, Descriptions, Space, Tag } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { disableEndpoint, enableEndpoint, setDefaultEndpoint, testEndpoint } from '../api/endpoints'
import { useEndpoint } from '../hooks/useEndpoints'
import { ApiError } from '../api/client'
import { ErrorState } from '../components/ErrorState'
import { EndpointTestAlert } from '../components/EndpointTestAlert'
import { TimeText } from '../components/TimeText'
import type { EndpointTestResult } from '../api/types'

export default function EndpointDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { data, error, isLoading } = useEndpoint(id)
  const [result, setResult] = useState<EndpointTestResult | null>(null)

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['endpoint', id] })
    queryClient.invalidateQueries({ queryKey: ['endpoints'] })
  }

  const run = async (action: () => Promise<unknown>, okText: string) => {
    try {
      await action()
      message.success(okText)
      refresh()
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : 'Operation failed')
    }
  }

  return (
    <Card loading={isLoading} title="Endpoint details" extra={<Button onClick={() => navigate('/endpoints')}>Back to list</Button>}>
      <ErrorState error={error} />
      <EndpointTestAlert result={result} />
      {data ? (
        <>
          <Descriptions bordered column={2} size="small">
            <Descriptions.Item label="Name">{data.name}</Descriptions.Item>
            <Descriptions.Item label="Default">
              {data.is_default ? <Tag color="gold">Default</Tag> : 'No'}
            </Descriptions.Item>
            <Descriptions.Item label="Base URL" span={2}>
              {data.base_url}
            </Descriptions.Item>
            <Descriptions.Item label="Auth type">
              {data.auth_type === 'basic' ? `Basic (${data.auth_username ?? 'opencode'})` : 'None'}
            </Descriptions.Item>
            <Descriptions.Item label="Password">
              {data.has_password ? 'Configured (never displayed)' : 'Not configured'}
            </Descriptions.Item>
            <Descriptions.Item label="Enabled">{data.enabled ? 'Yes' : 'No'}</Descriptions.Item>
            <Descriptions.Item label="Tasks">{data.task_count}</Descriptions.Item>
            <Descriptions.Item label="Last test">{data.last_test_result ?? 'Not tested'}</Descriptions.Item>
            <Descriptions.Item label="Tested at">
              <TimeText value={data.last_test_at} showOffset />
            </Descriptions.Item>
            <Descriptions.Item label="Test message" span={2}>
              {data.last_test_message ?? '—'}
            </Descriptions.Item>
            <Descriptions.Item label="Description" span={2}>
              {data.description ?? '—'}
            </Descriptions.Item>
          </Descriptions>
          <Space style={{ marginTop: 16 }} wrap>
            <Button onClick={() => navigate(`/endpoints/${data.id}/edit`)}>Edit</Button>
            <Button
              onClick={async () => {
                try {
                  setResult(await testEndpoint({ endpoint_id: data.id, auth_type: data.auth_type }))
                  refresh()
                } catch (err) {
                  message.error(err instanceof ApiError ? err.message : 'Test failed')
                }
              }}
            >
              Test connection
            </Button>
            {!data.is_default ? (
              <Button onClick={() => run(() => setDefaultEndpoint(data.id), 'Set as default')}>Set as default</Button>
            ) : null}
            <Button
              onClick={() =>
                run(
                  () => (data.enabled ? disableEndpoint(data.id) : enableEndpoint(data.id)),
                  data.enabled ? 'Disabled' : 'Enabled',
                )
              }
            >
              {data.enabled ? 'Disable' : 'Enable'}
            </Button>
          </Space>
        </>
      ) : null}
    </Card>
  )
}
