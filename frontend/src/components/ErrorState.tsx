import { Alert } from 'antd'
import { ApiError } from '../api/client'

export function ErrorState({ error }: { error: unknown }) {
  if (!error) return null
  const message = error instanceof ApiError ? error.message : String(error)
  return <Alert type="error" showIcon message="Request failed" description={message} style={{ marginBottom: 16 }} />
}
