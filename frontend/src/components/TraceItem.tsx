import { Collapse, Descriptions, Space, Tag, Typography } from 'antd'
import type { TraceItem as TraceItemType } from '../api/types'
import { DiffView } from './DiffView'
import { TimeText } from './TimeText'
import { prettyJson } from '../utils/format'
import { formatDuration } from '../utils/time'

const KIND_LABELS: Record<string, string> = {
  user_message: 'Prompt',
  assistant_message: 'Assistant',
  tool: 'Tool',
  skill: 'Skill',
  file: 'File',
  permission: 'Permission',
  error: 'Error',
  system: 'System',
}

const KIND_COLORS: Record<string, string> = {
  user_message: 'geekblue',
  assistant_message: 'purple',
  tool: 'blue',
  skill: 'cyan',
  file: 'gold',
  permission: 'orange',
  error: 'red',
  system: 'default',
}

function statusColor(status: string | null): string {
  if (status === 'completed') return 'green'
  if (status === 'failed') return 'red'
  if (status === 'rejected') return 'red'
  if (status === 'running') return 'blue'
  if (status === 'pending') return 'default'
  return 'default'
}

export function TraceItem({ item }: { item: TraceItemType }) {
  const header = (
    <Space wrap size="small">
      <Tag color={KIND_COLORS[item.kind] ?? 'default'}>{KIND_LABELS[item.kind] ?? item.kind}</Tag>
      {item.name ? <Typography.Text strong>{item.name}</Typography.Text> : null}
      {item.status ? <Tag color={statusColor(item.status)}>{item.status}</Tag> : null}
      <Typography.Text type="secondary">
        <TimeText value={item.started_at ?? null} />
      </Typography.Text>
      {item.duration_ms !== null ? (
        <Typography.Text type="secondary">{formatDuration(item.duration_ms)}</Typography.Text>
      ) : null}
    </Space>
  )

  return (
    <Collapse
      size="small"
      items={[
        {
          key: item.id,
          label: header,
          children: (
            <Space direction="vertical" style={{ width: '100%' }} size="small">
              <Descriptions size="small" column={2}>
                <Descriptions.Item label="External ID">{item.external_id}</Descriptions.Item>
                <Descriptions.Item label="Parent entry">{item.parent_external_id ?? '—'}</Descriptions.Item>
                <Descriptions.Item label="Started at">
                  <TimeText value={item.started_at} />
                </Descriptions.Item>
                <Descriptions.Item label="Ended at">
                  <TimeText value={item.ended_at} />
                </Descriptions.Item>
              </Descriptions>
              {item.input !== null && item.input !== undefined ? (
                <div>
                  <Typography.Text strong>Input</Typography.Text>
                  <pre style={{ margin: 0, maxHeight: 240, overflow: 'auto' }}>{prettyJson(item.input)}</pre>
                </div>
              ) : null}
              {item.kind === 'file' ? <DiffView patch={item.output} /> : null}
              {item.kind !== 'file' && item.output ? (
                <div>
                  <Typography.Text strong>Output</Typography.Text>
                  <pre style={{ margin: 0, maxHeight: 320, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{item.output}</pre>
                </div>
              ) : null}
              {item.error ? (
                <div>
                  <Typography.Text type="danger" strong>
                    Error
                  </Typography.Text>
                  <pre style={{ margin: 0, color: '#a8071a', whiteSpace: 'pre-wrap' }}>{item.error}</pre>
                </div>
              ) : null}
              {item.metadata && Object.keys(item.metadata).length > 0 ? (
                <div>
                  <Typography.Text type="secondary">Metadata</Typography.Text>
                  <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{prettyJson(item.metadata)}</pre>
                </div>
              ) : null}
            </Space>
          ),
        },
      ]}
    />
  )
}
