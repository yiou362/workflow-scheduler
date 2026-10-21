import { Alert } from 'antd'
import type { EndpointTestResult } from '../api/types'

const TYPES: Record<string, 'success' | 'error' | 'warning' | 'info'> = {
  success: 'success',
  auth_failed: 'error',
  unreachable: 'error',
  timeout: 'warning',
  service_error: 'error',
  unsupported: 'warning',
}

export function EndpointTestAlert({ result }: { result: EndpointTestResult | null }) {
  if (!result) return null
  return (
    <Alert
      style={{ marginBottom: 12 }}
      type={TYPES[result.result] ?? 'info'}
      showIcon
      message={result.message}
      description={result.version ? `OpenCode ${result.version}` : undefined}
    />
  )
}
