import { Alert, AutoComplete, DatePicker, Form, Input, InputNumber, Select, Space, Switch, Typography } from 'antd'
import type { FormInstance } from 'antd'
import type { Dayjs } from 'dayjs'
import { useEffect, useState } from 'react'
import { SchedulePreview } from './SchedulePreview'
import { fetchOptions } from '../api/endpoints'
import type { AgentOption, ModelOption, ScheduleType } from '../api/types'

interface Props {
  form: FormInstance
  utcOffset: string
}

export function ScheduleForm({ form, utcOffset }: Props) {
  const enabled = (Form.useWatch('schedule_enabled', form) ?? false) as boolean
  const type = (Form.useWatch('schedule_type', form) ?? 'none') as ScheduleType
  const cron = Form.useWatch('cron_expression', form) as string | undefined
  const runAt = Form.useWatch('run_at', form) as Dayjs | undefined
  const intervalSeconds = Form.useWatch('interval_seconds', form) as number | undefined

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Alert type="info" showIcon message={`All times are interpreted as UTC${utcOffset}`} />
      <Space wrap>
        <Form.Item name="schedule_enabled" label="Enable automatic schedule" valuePropName="checked">
          <Switch disabled={type === 'none'} />
        </Form.Item>
        <Form.Item name="schedule_type" label="Schedule type">
          <Select
            style={{ width: 200 }}
            options={[
              { value: 'none', label: 'No automatic schedule' },
              { value: 'cron', label: 'Cron' },
              { value: 'once', label: 'Once' },
              { value: 'interval', label: 'Fixed interval' },
            ]}
            onChange={(value: ScheduleType) => {
              if (value === 'none') form.setFieldValue('schedule_enabled', false)
            }}
          />
        </Form.Item>
      </Space>
      {type === 'cron' ? (
        <Form.Item
          name="cron_expression"
          label="Cron expression"
          rules={[
            { required: true, message: 'Please enter a cron expression' },
            {
              validator: async (_, value: string) => {
                if (!value) return
                if (value.trim().split(/\s+/).length !== 5) {
                  throw new Error('A cron expression must have 5 fields (minute hour day month weekday)')
                }
              },
            },
          ]}
        >
          <Input placeholder="0 9 * * *" style={{ width: 240 }} />
        </Form.Item>
      ) : null}
      {type === 'once' ? (
        <Form.Item
          name="run_at"
          label="Run at"
          rules={[{ required: true, message: 'Please pick a run time' }]}
        >
          <DatePicker showTime format="YYYY-MM-DD HH:mm:ss" />
        </Form.Item>
      ) : null}
      {type === 'interval' ? (
        <Form.Item
          name="interval_seconds"
          label="Interval (seconds)"
          rules={[{ required: true, message: 'Please enter the interval in seconds' }]}
        >
          <InputNumber min={60} style={{ width: 200 }} />
        </Form.Item>
      ) : null}
      <Typography.Text type="secondary">
        Preview the next 5 run times before saving; the preview does not write to the database.
      </Typography.Text>
      <SchedulePreview
        enabled={enabled && type !== 'none'}
        utcOffset={utcOffset}
        values={{ type, cron, runAt, intervalSeconds }}
      />
    </Space>
  )
}

interface ModelSelectProps {
  endpointId?: string
  workingDirectory?: string
  onModels?: (models: ModelOption[], agents: AgentOption[], warning: string | null) => void
}

export function useOptions({ endpointId, workingDirectory, onModels }: ModelSelectProps) {
  const [models, setModels] = useState<ModelOption[]>([])
  const [agents, setAgents] = useState<AgentOption[]>([])
  const [warning, setWarning] = useState<string | null>(null)
  useEffect(() => {
    if (!endpointId || !workingDirectory) return
    let cancelled = false
    fetchOptions(endpointId, workingDirectory)
      .then((response) => {
        if (cancelled) return
        setModels(response.models)
        setAgents(response.agents)
        setWarning(response.warning)
        onModels?.(response.models, response.agents, response.warning)
      })
      .catch(() => {
        if (!cancelled) setWarning('Could not load the model list from the endpoint; enter it manually')
      })
    return () => {
      cancelled = true
    }
  }, [endpointId, workingDirectory, onModels])
  return { models, agents, warning }
}

export function ModelSelect({
  value,
  onChange,
  options,
  placeholder,
}: {
  value?: string
  onChange?: (value: string) => void
  options: { value: string; label: string }[]
  placeholder?: string
}) {
  return (
    <AutoComplete
      allowClear
      value={value}
      onChange={onChange}
      options={options}
      placeholder={placeholder}
      filterOption={(input, option) =>
        String(option?.label ?? '').toLowerCase().includes(input.toLowerCase())
      }
      style={{ width: '100%' }}
    />
  )
}
