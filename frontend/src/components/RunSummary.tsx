import { Descriptions, Space, Typography } from 'antd'
import type { ReactNode } from 'react'
import type { Run } from '../api/types'
import { StatusTag } from './StatusTag'
import { TimeText } from './TimeText'
import { TRIGGER_LABELS } from '../utils/format'
import { formatDuration } from '../utils/time'

interface Props {
  run: Run
  actions?: ReactNode
}

export function RunSummary({ run, actions }: Props) {
  return (
    <Space direction="vertical" style={{ width: '100%' }} size="small">
      {actions ? <div>{actions}</div> : null}
      <Descriptions bordered size="small" column={{ xs: 1, md: 2, lg: 3 }}>
        <Descriptions.Item label="Task">{run.task_name}</Descriptions.Item>
        <Descriptions.Item label="Status">
          <StatusTag status={run.status} />
        </Descriptions.Item>
        <Descriptions.Item label="Trigger source">{TRIGGER_LABELS[run.trigger_source] ?? run.trigger_source}</Descriptions.Item>
        <Descriptions.Item label="Endpoint">
          {run.endpoint.name}
          <Typography.Text type="secondary"> {run.endpoint.base_url}</Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="Working directory">{run.working_directory}</Descriptions.Item>
        <Descriptions.Item label="Provider / model">
          {run.provider_id} / {run.model_id}
          {run.model_variant ? ` (${run.model_variant})` : ''}
        </Descriptions.Item>
        <Descriptions.Item label="Agent">{run.agent ?? 'server default'}</Descriptions.Item>
        <Descriptions.Item label="Started at">
          <TimeText value={run.started_at} offset={run.utc_offset} showOffset />
        </Descriptions.Item>
        <Descriptions.Item label="Finished at">
          <TimeText value={run.finished_at} offset={run.utc_offset} showOffset />
        </Descriptions.Item>
        <Descriptions.Item label="Total duration">{formatDuration(run.duration_ms)}</Descriptions.Item>
        <Descriptions.Item label="Queue wait">{formatDuration(run.queue_wait_ms)}</Descriptions.Item>
        <Descriptions.Item label="Schedule">{run.schedule_summary}</Descriptions.Item>
        <Descriptions.Item label="Session">
          {run.opencode_session_id ?? 'not created'}
        </Descriptions.Item>
      </Descriptions>
    </Space>
  )
}
