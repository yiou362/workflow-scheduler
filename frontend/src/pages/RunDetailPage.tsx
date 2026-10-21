import { useMemo, useState } from 'react'
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Modal,
  Select,
  Space,
  Tabs,
  Typography,
} from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { cancelRun, replyPermission, rerunRun } from '../api/endpoints'
import { useLogs, useRun, useTrace } from '../hooks/useRuns'
import { useEndpoints } from '../hooks/useEndpoints'
import { ApiError } from '../api/client'
import { ErrorState } from '../components/ErrorState'
import { RunSummary } from '../components/RunSummary'
import { TraceView } from '../components/TraceView'
import { LogsPanel } from '../components/LogsPanel'
import { ConfigSnapshot } from '../components/ConfigSnapshot'
import { PermissionModal } from '../components/PermissionModal'

const TERMINAL = ['completed', 'failed', 'cancelled', 'timeout', 'skipped', 'unknown']

export default function RunDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const { data, error, isLoading } = useRun(id)
  const run = data?.run
  const active = run ? !TERMINAL.includes(run.status) : false
  const trace = useTrace(id, active)
  const logs = useLogs(id, active)
  const endpoints = useEndpoints()

  const [permissionOpen, setPermissionOpen] = useState(false)
  const [rerunOpen, setRerunOpen] = useState(false)
  const [rerunEndpoint, setRerunEndpoint] = useState<string | undefined>()

  const pending = data?.pending_permissions ?? []
  const permissionActionsDisabled = run ? TERMINAL.includes(run.status) : true

  const endpointOptions = useMemo(
    () =>
      (endpoints.data?.items ?? [])
        .filter((item) => item.enabled)
        .map((item) => ({ value: item.id, label: item.name })),
    [endpoints.data],
  )

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['run', id] })
    queryClient.invalidateQueries({ queryKey: ['runs'] })
    queryClient.invalidateQueries({ queryKey: ['dashboard'] })
  }

  const doCancel = () => {
    modal.confirm({
      title: 'Cancel this run?',
      content:
        'Cancelling cannot undo file changes, messages sent, or external calls that already happened. The run is not shown as cancelled until the stop is confirmed.',
      okText: 'Request cancel',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const response = await cancelRun(id as string)
          message.info(response.message)
          refresh()
        } catch (err) {
          message.error(err instanceof ApiError ? err.message : 'Cancel failed')
        }
      },
    })
  }

  const doRerun = async () => {
    try {
      const response = await rerunRun(id as string, rerunEndpoint)
      message.success(response.message)
      setRerunOpen(false)
      navigate(`/runs/${response.run.id}`)
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : 'Rerun failed')
    }
  }

  const submitPermission = async (
    requestId: string,
    decision: 'once' | 'always' | 'reject',
    text?: string,
  ) => {
    try {
      await replyPermission(id as string, requestId, decision, text)
      message.success('Permission reply sent')
      setPermissionOpen(false)
      refresh()
      queryClient.invalidateQueries({ queryKey: ['run', id, 'trace'] })
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : 'Permission reply failed')
    }
  }

  const finalText = run?.final_response
    ? run.final_response
    : 'This run has no usable final response.'

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <ErrorState error={error} />
      <Card
        loading={isLoading}
        title="Run details"
        extra={
          <Space wrap>
            <Button onClick={() => navigate('/runs')}>Back to runs</Button>
            {run && !TERMINAL.includes(run.status) ? (
              <Button danger onClick={doCancel}>
                Cancel run
              </Button>
            ) : null}
            {run && TERMINAL.includes(run.status) ? (
              <Button type="primary" onClick={() => setRerunOpen(true)}>
                Rerun
              </Button>
            ) : null}
          </Space>
        }
      >
        {run ? <RunSummary run={run} /> : null}
      </Card>

      {run?.error_type ? (
        <Alert
          type="error"
          showIcon
          message={`Run failed: ${run.error_type}`}
          description={
            <span>
              Phase: {run.error_phase ?? 'unknown'}; error: {run.error_message ?? 'no details'};
              rerunnable: yes
            </span>
          }
        />
      ) : null}

      {pending.length > 0 ? (
        <Alert
          type="warning"
          showIcon
          message={`${pending.length} pending permission request(s)`}
          description="This system never approves permissions automatically. Handle them, or cancel this run."
          action={
            <Button size="small" type="primary" onClick={() => setPermissionOpen(true)}>
              Handle permissions
            </Button>
          }
        />
      ) : null}

      <Card size="small" title="Prompt actually sent by this run">
        <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{run?.prompt ?? ''}</pre>
      </Card>

      <Card size="small" title="Trace">
        <Tabs
          items={[
            {
              key: 'trace',
              label: 'Execution trace',
              children: trace.data ? (
                <TraceView
                  items={trace.data.items}
                  integrity={trace.data.integrity}
                  gapCount={trace.data.gap_count}
                />
              ) : (
                <Typography.Text type="secondary">Loading…</Typography.Text>
              ),
            },
            {
              key: 'logs',
              label: 'Run log',
              children: <LogsPanel logs={logs.data?.items ?? []} />,
            },
          ]}
        />
      </Card>

      <Card size="small" title="Final result" extra={<Typography.Text type="secondary">Source: last assistant text</Typography.Text>}>
        <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{finalText}</pre>
        {run?.final_response_truncated ? <Alert type="warning" showIcon message="Final response was truncated" /> : null}
      </Card>

      <Card size="small" title="Usage" extra={<Typography.Text type="secondary">Missing values show "not reported"; nothing is estimated</Typography.Text>}>
        <Descriptions size="small" column={3}>
          <Descriptions.Item label="Input tokens">{run?.usage.input_tokens ?? 'not reported'}</Descriptions.Item>
          <Descriptions.Item label="Output tokens">{run?.usage.output_tokens ?? 'not reported'}</Descriptions.Item>
          <Descriptions.Item label="Reasoning tokens">{run?.usage.reasoning_tokens ?? 'not reported'}</Descriptions.Item>
          <Descriptions.Item label="Cache read">{run?.usage.cache_read_tokens ?? 'not reported'}</Descriptions.Item>
          <Descriptions.Item label="Cache write">{run?.usage.cache_write_tokens ?? 'not reported'}</Descriptions.Item>
          <Descriptions.Item label="Cost (USD)">{run?.usage.cost_usd ?? 'not reported'}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card size="small" title="Config snapshot">
        {run ? <ConfigSnapshot snapshot={run.config_snapshot} /> : null}
      </Card>

      <PermissionModal
        open={permissionOpen}
        permissions={pending}
        disabled={permissionActionsDisabled}
        onClose={() => setPermissionOpen(false)}
        onSubmit={submitPermission}
      />

      <Modal
        open={rerunOpen}
        title="Rerun"
        okText="Create new run"
        onCancel={() => setRerunOpen(false)}
        onOk={doRerun}
      >
        <Typography.Paragraph>
          The config snapshot of the original run is used by default. If that endpoint has been deleted
          or disabled, pick an available endpoint; the new run records this override and the original
          run is left untouched.
        </Typography.Paragraph>
        <Select
          allowClear
          style={{ width: '100%' }}
          placeholder="(Optional) choose another available endpoint"
          value={rerunEndpoint}
          onChange={setRerunEndpoint}
          options={endpointOptions}
        />
      </Modal>
    </Space>
  )
}
