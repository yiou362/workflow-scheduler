import { useState } from 'react'
import { Button, Descriptions, Input, Modal, Space, Tag, Typography } from 'antd'
import type { PendingPermission } from '../api/types'
import { prettyJson } from '../utils/format'

interface Props {
  open: boolean
  permissions: PendingPermission[]
  disabled?: boolean
  onClose: () => void
  onSubmit: (requestId: string, decision: 'once' | 'always' | 'reject', message?: string) => Promise<void>
}

export function PermissionModal({ open, permissions, disabled, onClose, onSubmit }: Props) {
  const [messages, setMessages] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)

  const submit = async (requestId: string, decision: 'once' | 'always' | 'reject') => {
    setBusy(requestId)
    try {
      await onSubmit(requestId, decision, decision === 'reject' ? messages[requestId] : undefined)
    } finally {
      setBusy(null)
    }
  }

  return (
    <Modal open={open} title="Pending permissions" footer={null} onCancel={onClose} width={720}>
      {permissions.length === 0 ? (
        <Typography.Text>There are no pending permission requests.</Typography.Text>
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          {permissions.map((permission) => (
            <div key={permission.request_id} style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 12 }}>
              <Space wrap>
                <Tag color="orange">{permission.action}</Tag>
                <Typography.Text type="secondary">{permission.request_id}</Typography.Text>
              </Space>
              <Descriptions size="small" column={1} style={{ marginTop: 8 }}>
                <Descriptions.Item label="Resource">
                  <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{prettyJson(permission.input)}</pre>
                </Descriptions.Item>
                <Descriptions.Item label="Request info">
                  <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{prettyJson(permission.metadata)}</pre>
                </Descriptions.Item>
              </Descriptions>
              <Space style={{ marginTop: 8 }} wrap>
                <Button type="primary" disabled={disabled} loading={busy === permission.request_id} onClick={() => submit(permission.request_id, 'once')}>
                  Allow once
                </Button>
                <Button disabled={disabled} loading={busy === permission.request_id} onClick={() => submit(permission.request_id, 'always')}>
                  Always
                </Button>
                <Button danger disabled={disabled} loading={busy === permission.request_id} onClick={() => submit(permission.request_id, 'reject')}>
                  Reject
                </Button>
              </Space>
              <Input.TextArea
                style={{ marginTop: 8 }}
                rows={2}
                placeholder="Rejection reason (optional)"
                value={messages[permission.request_id] ?? ''}
                onChange={(event) => setMessages((prev) => ({ ...prev, [permission.request_id]: event.target.value }))}
              />
            </div>
          ))}
        </Space>
      )}
    </Modal>
  )
}
