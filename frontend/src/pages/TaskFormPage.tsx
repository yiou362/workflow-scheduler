import { useEffect, useMemo, useState } from 'react'
import { Alert, App, AutoComplete, Button, Card, Form, Input, InputNumber, Select, Space, Typography } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import type { Dayjs } from 'dayjs'
import type { ScheduleType, TaskPayload } from '../api/types'
import { createTask, updateTask } from '../api/endpoints'
import { useTask } from '../hooks/useTasks'
import { useEndpoints } from '../hooks/useEndpoints'
import { useMeta } from '../hooks/useMeta'
import { ApiError } from '../api/client'
import { ErrorState } from '../components/ErrorState'
import { ScheduleForm, useOptions } from '../components/ScheduleForm'
import { wallClockToIso, dayjs } from '../utils/time'

interface FormValues {
  name: string
  description?: string
  tags: string[]
  endpoint_id: string
  working_directory: string
  provider_id: string
  model_id: string
  model_variant?: string
  agent?: string
  prompt: string
  status: 'enabled' | 'disabled'
  schedule_enabled: boolean
  schedule_type: ScheduleType
  cron_expression?: string
  run_at?: Dayjs
  interval_seconds?: number
  overlap_policy: 'queue' | 'skip'
  missed_policy: 'skip' | 'run_once'
  timeout_minutes: number
}

export default function TaskFormPage() {
  const { id } = useParams()
  const editing = Boolean(id)
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [form] = Form.useForm<FormValues>()
  const { data: task, error: taskError, isLoading } = useTask(id)
  const endpoints = useEndpoints()
  const meta = useMeta()
  const offset = meta.data?.utc_offset ?? '+08:00'
  const [saving, setSaving] = useState(false)

  const endpointId = Form.useWatch('endpoint_id', form) as string | undefined
  const workingDirectory = Form.useWatch('working_directory', form) as string | undefined
  const prompt = Form.useWatch('prompt', form) as string | undefined
  const { models, agents, warning } = useOptions({ endpointId, workingDirectory })

  const providerOptions = useMemo(
    () => Array.from(new Set(models.map((item) => item.provider_id))).map((value) => ({ value })),
    [models],
  )
  const modelOptions = useMemo(
    () =>
      models.map((item) => ({
        value: item.model_id,
        label: `${item.provider_id} / ${item.name ?? item.model_id}`,
      })),
    [models],
  )
  const variantOptions = useMemo(
    () =>
      Array.from(new Set(models.flatMap((item) => item.variants))).map((value) => ({ value })),
    [models],
  )
  const agentOptions = useMemo(() => agents.map((item) => ({ value: item.id })), [agents])

  useEffect(() => {
    if (editing || !endpoints.data || form.getFieldValue('endpoint_id')) return
    const items = endpoints.data.items.filter((item) => item.enabled)
    const preferred = items.find((item) => item.is_default) ?? items[0]
    if (preferred) form.setFieldValue('endpoint_id', preferred.id)
  }, [editing, endpoints.data, form])

  useEffect(() => {
    if (!task) return
    form.setFieldsValue({
      name: task.name,
      description: task.description ?? undefined,
      tags: task.tags,
      endpoint_id: task.endpoint_id,
      working_directory: task.working_directory,
      provider_id: task.provider_id,
      model_id: task.model_id,
      model_variant: task.model_variant ?? undefined,
      agent: task.agent ?? undefined,
      prompt: task.prompt,
      status: task.status === 'archived' ? 'disabled' : task.status,
      schedule_enabled: task.schedule_enabled,
      schedule_type: task.schedule_type,
      cron_expression: task.cron_expression ?? undefined,
      run_at: task.run_at ? dayjs.utc(task.run_at).utcOffset(offset) : undefined,
      interval_seconds: task.interval_seconds ?? undefined,
      overlap_policy: task.overlap_policy,
      missed_policy: task.missed_policy,
      timeout_minutes: task.timeout_minutes,
    })
  }, [task, form, offset])

  const submit = async () => {
    try {
      const values = await form.validateFields()
      if (!values.prompt || !values.prompt.trim()) {
        form.setFields([{ name: 'prompt', errors: ['Prompt cannot be empty'] }])
        return
      }
      const payload: TaskPayload = {
        name: values.name,
        description: values.description || null,
        tags: values.tags ?? [],
        endpoint_id: values.endpoint_id,
        working_directory: values.working_directory,
        provider_id: values.provider_id,
        model_id: values.model_id,
        model_variant: values.model_variant || null,
        agent: values.agent || null,
        prompt: values.prompt,
        status: values.status,
        schedule_enabled: values.schedule_type === 'none' ? false : Boolean(values.schedule_enabled),
        schedule_type: values.schedule_type,
        cron_expression: values.schedule_type === 'cron' ? values.cron_expression ?? null : null,
        run_at:
          values.schedule_type === 'once' && values.run_at
            ? wallClockToIso(values.run_at, values.run_at, offset)
            : null,
        interval_seconds: values.schedule_type === 'interval' ? values.interval_seconds ?? null : null,
        overlap_policy: values.overlap_policy,
        missed_policy: values.missed_policy,
        timeout_minutes: values.timeout_minutes,
      }
      setSaving(true)
      const saved = editing && id ? await updateTask(id, payload) : await createTask(payload)
      message.success(editing ? 'Task updated' : 'Task created')
      navigate(`/tasks/${saved.id}`)
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.details) {
          form.setFields(
            Object.entries(err.details).map(([name, msg]) => ({
              name: name as keyof FormValues,
              errors: [msg],
            })),
          )
        }
        message.error(err.message)
      }
    } finally {
      setSaving(false)
    }
  }

  const archived = task?.status === 'archived'

  return (
    <Card
      loading={isLoading}
      title={editing ? 'Edit task' : 'New task'}
      extra={<Button onClick={() => navigate(-1)}>Back</Button>}
    >
      <ErrorState error={taskError} />
      {archived ? <Alert type="warning" showIcon message="Archived tasks cannot be edited; restore the task first on its details page" style={{ marginBottom: 16 }} /> : null}
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          tags: [],
          status: 'enabled',
          schedule_enabled: false,
          schedule_type: 'none',
          overlap_policy: 'queue',
          missed_policy: 'skip',
          timeout_minutes: 60,
        }}
      >
        <Card size="small" title="Basics" style={{ marginBottom: 16 }}>
          <Form.Item name="name" label="Name" rules={[{ required: true, message: 'Please enter a name' }]}>
            <Input maxLength={120} />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <Input.TextArea rows={2} maxLength={2000} />
          </Form.Item>
          <Form.Item name="tags" label="Tags">
            <Select mode="tags" tokenSeparators={[',']} placeholder="Type and press Enter to add" maxCount={20} />
          </Form.Item>
          <Form.Item name="status" label="Status">
            <Select
              options={[
                { value: 'enabled', label: 'Enabled' },
                { value: 'disabled', label: 'Disabled' },
              ]}
            />
          </Form.Item>
        </Card>

        <Card size="small" title="Execution target" style={{ marginBottom: 16 }}>
          <Form.Item
            name="endpoint_id"
            label="Endpoint"
            rules={[{ required: true, message: 'Please select an endpoint' }]}
          >
            <Select
              placeholder={endpoints.data?.items.length ? 'Select an endpoint' : 'Configure an endpoint first'}
              options={(endpoints.data?.items ?? [])
                .filter((item) => item.enabled || item.id === task?.endpoint_id)
                .map((item) => ({ value: item.id, label: `${item.name}${item.enabled ? '' : ' (disabled)'}` }))}
            />
          </Form.Item>
          {!endpoints.isLoading && (endpoints.data?.items.length ?? 0) === 0 ? (
            <Alert type="warning" showIcon message="Configure an endpoint first" style={{ marginBottom: 16 }} />
          ) : null}
          <Form.Item
            name="working_directory"
            label="Working directory"
            rules={[{ required: true, message: 'Please enter the working directory' }]}
            extra="Must be a path on the OpenCode host; this system does not verify that it exists"
          >
            <Input placeholder="/workspace/rates-report" />
          </Form.Item>
          <Space style={{ width: '100%' }} size="middle" align="start">
            <Form.Item name="provider_id" label="Provider" rules={[{ required: true, message: 'Please enter a provider' }]}>
              <AutoComplete options={providerOptions} style={{ width: 220 }} placeholder="lps" />
            </Form.Item>
            <Form.Item name="model_id" label="Model" rules={[{ required: true, message: 'Please enter a model' }]}>
              <AutoComplete
                options={modelOptions}
                style={{ width: 320 }}
                placeholder="Qwen/Qwen3.6-35B-A3B-FP8"
                filterOption={(input, option) =>
                  String(option?.label ?? '').toLowerCase().includes(input.toLowerCase())
                }
              />
            </Form.Item>
          </Space>
          <Space style={{ width: '100%' }} size="middle">
            <Form.Item name="model_variant" label="Model variant">
              <AutoComplete options={variantOptions} style={{ width: 200 }} placeholder="thinking / no_thinking" />
            </Form.Item>
            <Form.Item name="agent" label="Agent (optional)">
              <AutoComplete options={agentOptions} style={{ width: 200 }} placeholder="build" />
            </Form.Item>
          </Space>
          {warning ? <Alert type="warning" showIcon message={warning} style={{ marginBottom: 16 }} /> : null}
        </Card>

        <Card size="small" title="Prompt" style={{ marginBottom: 16 }}>
          <Form.Item
            name="prompt"
            label="Full prompt sent to OpenCode"
            rules={[{ required: true, message: 'Prompt cannot be empty' }]}
            extra="Stored and sent verbatim; nothing hidden is appended"
          >
            <Input.TextArea rows={6} />
          </Form.Item>
          <Typography.Text type="secondary">Characters: {prompt?.length ?? 0}</Typography.Text>
        </Card>

        <Card size="small" title="Schedule" style={{ marginBottom: 16 }}>
          <ScheduleForm form={form} utcOffset={offset} />
        </Card>

        <Card size="small" title="Execution policy" style={{ marginBottom: 16 }}>
          <Space wrap size="middle">
            <Form.Item name="overlap_policy" label="Overlap policy">
              <Select
                style={{ width: 190 }}
                options={[
                  { value: 'queue', label: 'Queue' },
                  { value: 'skip', label: 'Skip (record and skip)' },
                ]}
              />
            </Form.Item>
            <Form.Item name="missed_policy" label="Missed policy">
              <Select
                style={{ width: 190 }}
                options={[
                  { value: 'skip', label: 'Skip (no catch-up)' },
                  { value: 'run_once', label: 'Run once (one catch-up)' },
                ]}
              />
            </Form.Item>
            <Form.Item name="timeout_minutes" label="Timeout (minutes)">
              <InputNumber min={1} max={10080} />
            </Form.Item>
          </Space>
        </Card>

        <Space>
          <Button type="primary" onClick={submit} loading={saving} disabled={archived}>
            Save
          </Button>
          <Button onClick={() => navigate(-1)}>Cancel</Button>
        </Space>
      </Form>
    </Card>
  )
}
