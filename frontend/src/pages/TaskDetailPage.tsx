import { Alert, App, Button, Card, Descriptions, Popconfirm, Space, Tag, Typography } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  archiveTask,
  copyTask,
  disableTask,
  enableTask,
  restoreTask,
  runTaskNow,
} from '../api/endpoints'
import { useTask } from '../hooks/useTasks'
import { ApiError } from '../api/client'
import { ErrorState } from '../components/ErrorState'
import { StatusTag, TaskStatusTag } from '../components/StatusTag'
import { TimeText } from '../components/TimeText'
import { SCHEDULE_TYPE_LABELS } from '../utils/format'

export default function TaskDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { data, error, isLoading } = useTask(id)

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['task', id] })
    queryClient.invalidateQueries({ queryKey: ['tasks'] })
    queryClient.invalidateQueries({ queryKey: ['dashboard'] })
  }

  const action = (fn: () => Promise<unknown>, ok: string) =>
    fn()
      .then(() => {
        message.success(ok)
        refresh()
      })
      .catch((err) => message.error(err instanceof ApiError ? err.message : 'Operation failed'))

  const runMutation = useMutation({
    mutationFn: runTaskNow,
    onSuccess: (response) => {
      message.success(response.message)
      navigate(`/runs/${response.run.id}`)
    },
    onError: (err) => message.error(err instanceof ApiError ? err.message : 'Execution failed'),
  })

  const copyMutation = useMutation({
    mutationFn: copyTask,
    onSuccess: (copied) => {
      message.success('Task copied (disabled and not scheduled by default)')
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      navigate(`/tasks/${copied.id}`)
    },
    onError: (err) => message.error(err instanceof ApiError ? err.message : 'Copy failed'),
  })

  const archived = data?.status === 'archived'

  return (
    <Card
      loading={isLoading}
      title="Task details"
      extra={
        <Space wrap>
          <Button onClick={() => navigate('/tasks')}>Back to list</Button>
          {!archived ? <Button onClick={() => navigate(`/tasks/${id}/edit`)}>Edit</Button> : null}
          <Button onClick={() => copyMutation.mutate(id as string)} loading={copyMutation.isPending}>
            Copy
          </Button>
          {!archived ? (
            <Button
              type="primary"
              loading={runMutation.isPending}
              onClick={() => runMutation.mutate(id as string)}
            >
              Run now
            </Button>
          ) : null}
        </Space>
      }
    >
      <ErrorState error={error} />
      {data ? (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="Name">{data.name}</Descriptions.Item>
            <Descriptions.Item label="Status">
              <TaskStatusTag status={data.status} />
            </Descriptions.Item>
            <Descriptions.Item label="Endpoint">{data.endpoint_name ?? data.endpoint_id}</Descriptions.Item>
            <Descriptions.Item label="Working directory">{data.working_directory}</Descriptions.Item>
            <Descriptions.Item label="Provider / model">
              {data.provider_id} / {data.model_id}
            </Descriptions.Item>
            <Descriptions.Item label="Model variant / agent">
              {data.model_variant ?? '—'} / {data.agent ?? 'server default'}
            </Descriptions.Item>
            <Descriptions.Item label="Schedule type">{SCHEDULE_TYPE_LABELS[data.schedule_type]}</Descriptions.Item>
            <Descriptions.Item label="Automatic schedule">{data.schedule_enabled ? 'Enabled' : 'Off'}</Descriptions.Item>
            <Descriptions.Item label="Schedule detail">{data.schedule_summary}</Descriptions.Item>
            <Descriptions.Item label="Next run">
              <TimeText value={data.next_run_at} showOffset />
            </Descriptions.Item>
            <Descriptions.Item label="Overlap policy">{data.overlap_policy}</Descriptions.Item>
            <Descriptions.Item label="Missed policy">{data.missed_policy}</Descriptions.Item>
            <Descriptions.Item label="Timeout">{data.timeout_minutes} min</Descriptions.Item>
            <Descriptions.Item label="Tags">
              {data.tags.length > 0 ? data.tags.map((tag) => <Tag key={tag}>{tag}</Tag>) : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="Description" span={2}>
              {data.description ?? '—'}
            </Descriptions.Item>
          </Descriptions>

          <Card size="small" title="Stored prompt">
            <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{data.prompt}</pre>
          </Card>

          <Card
            size="small"
            title="Latest run"
            extra={
              data.last_run ? (
                <Button size="small" onClick={() => navigate(`/runs/${data.last_run?.id}`)}>
                  View details
                </Button>
              ) : null
            }
          >
            {data.last_run ? (
              <Space>
                <StatusTag status={data.last_run.status} />
                <TimeText value={data.last_run.started_at ?? data.last_run.created_at} showOffset />
              </Space>
            ) : (
              <Typography.Text type="secondary">No runs yet</Typography.Text>
            )}
          </Card>

          <Space wrap>
            {data.status !== 'archived' ? (
              <Button
                onClick={() =>
                  action(
                    () => (data.status === 'enabled' ? disableTask(data.id) : enableTask(data.id)),
                    data.status === 'enabled' ? 'Disabled' : 'Enabled',
                  )
                }
              >
                {data.status === 'enabled' ? 'Disable' : 'Enable'}
              </Button>
            ) : null}
            {data.status !== 'archived' ? (
              <Popconfirm
                title="Archive this task?"
                description="Archived tasks are no longer scheduled and cannot be run manually; historical runs are kept."
                onConfirm={() => action(() => archiveTask(data.id), 'Archived')}
              >
                <Button danger>Archive</Button>
              </Popconfirm>
            ) : (
              <Button onClick={() => action(() => restoreTask(data.id), 'Restored as disabled')}>Restore</Button>
            )}
          </Space>
          {archived ? <Alert type="info" showIcon message="An archived task keeps its run history, and historical runs can still be rerun." /> : null}
        </Space>
      ) : null}
    </Card>
  )
}
