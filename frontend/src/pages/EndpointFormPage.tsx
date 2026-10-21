import { useEffect, useState } from 'react'
import { App, Button, Card, Form, Input, Select, Space, Switch, Typography } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import type { EndpointPayload, EndpointTestResult } from '../api/types'
import { createEndpoint, testEndpoint, updateEndpoint } from '../api/endpoints'
import { useEndpoint } from '../hooks/useEndpoints'
import { ApiError } from '../api/client'
import { ErrorState } from '../components/ErrorState'
import { EndpointTestAlert } from '../components/EndpointTestAlert'

interface FormValues {
  name: string
  description?: string
  base_url: string
  auth_type: 'none' | 'basic'
  auth_username?: string
  password?: string
  enabled: boolean
}

export default function EndpointFormPage() {
  const { id } = useParams()
  const editing = Boolean(id)
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [form] = Form.useForm<FormValues>()
  const { data: endpoint, error } = useEndpoint(id)
  const [result, setResult] = useState<EndpointTestResult | null>(null)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const authType = Form.useWatch('auth_type', form) ?? 'none'

  useEffect(() => {
    if (!endpoint) return
    form.setFieldsValue({
      name: endpoint.name,
      description: endpoint.description ?? undefined,
      base_url: endpoint.base_url,
      auth_type: endpoint.auth_type,
      auth_username: endpoint.auth_username ?? 'opencode',
      enabled: endpoint.enabled,
    })
  }, [endpoint, form])

  const buildPayload = (values: FormValues): EndpointPayload => ({
    name: values.name,
    description: values.description ?? null,
    base_url: values.base_url,
    auth_type: values.auth_type,
    auth_username: values.auth_type === 'basic' ? values.auth_username || 'opencode' : null,
    password: values.password || undefined,
    enabled: values.enabled,
  })

  const runTest = async () => {
    const values = await form.validateFields(['base_url', 'auth_type', 'auth_username'])
    setTesting(true)
    try {
      const response = await testEndpoint({
        endpoint_id: id,
        base_url: values.base_url,
        auth_type: values.auth_type,
        auth_username: values.auth_username,
        password: form.getFieldValue('password') || undefined,
      })
      setResult(response)
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : 'Connection test failed')
    } finally {
      setTesting(false)
    }
  }

  const submit = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      const payload = buildPayload(values)
      const saved = editing && id ? await updateEndpoint(id, payload) : await createEndpoint(payload)
      message.success(editing ? 'Endpoint updated' : 'Endpoint created')
      navigate(`/endpoints/${saved.id}`)
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

  return (
    <Card title={editing ? 'Edit endpoint' : 'New endpoint'} style={{ maxWidth: 760 }}>
      <ErrorState error={error} />
      <EndpointTestAlert result={result} />
      <Form form={form} layout="vertical" initialValues={{ auth_type: 'none', auth_username: 'opencode', enabled: true }}>
        <Form.Item name="name" label="Name" rules={[{ required: true, message: 'Please enter a name' }]}>
          <Input maxLength={120} />
        </Form.Item>
        <Form.Item name="description" label="Description">
          <Input.TextArea rows={2} maxLength={2000} />
        </Form.Item>
        <Form.Item
          name="base_url"
          label="Base URL"
          rules={[{ required: true, message: 'Please enter the base URL' }]}
          extra="Must start with http:// or https://; no username/password, query, or fragment"
        >
          <Input placeholder="http://127.0.0.1:4096" />
        </Form.Item>
        <Form.Item name="auth_type" label="Auth type" rules={[{ required: true }]}>
          <Select
            options={[
              { value: 'none', label: 'None' },
              { value: 'basic', label: 'Basic Authentication' },
            ]}
          />
        </Form.Item>
        {authType === 'basic' ? (
          <Space style={{ width: '100%' }} size="middle">
            <Form.Item name="auth_username" label="Username">
              <Input placeholder="opencode" />
            </Form.Item>
            <Form.Item
              name="password"
              label="Password"
              extra={editing ? 'Leave blank to keep the saved password' : undefined}
              rules={editing ? [] : [{ required: true, message: 'A password is required for new Basic auth endpoints' }]}
            >
              <Input.Password placeholder={editing ? 'Configured, leave blank to keep it' : ''} autoComplete="new-password" />
            </Form.Item>
          </Space>
        ) : null}
        <Form.Item name="enabled" label="Enabled" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Space>
          <Button onClick={runTest} loading={testing}>
            Test connection
          </Button>
          <Button type="primary" onClick={submit} loading={saving}>
            Save
          </Button>
          <Button onClick={() => navigate(-1)}>Cancel</Button>
        </Space>
      </Form>
      {editing ? <Typography.Text type="secondary">Passwords are write-only and never displayed.</Typography.Text> : null}
    </Card>
  )
}
