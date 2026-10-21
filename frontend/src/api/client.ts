export class ApiError extends Error {
  status: number
  code: string
  details: Record<string, string> | null

  constructor(status: number, code: string, message: string, details?: Record<string, string> | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details ?? null
  }
}

interface ErrorEnvelope {
  error?: {
    code?: string
    message?: string
    details?: Record<string, string>
  }
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  let response: Response
  try {
    response = await fetch(path, { ...init, headers, credentials: 'same-origin' })
  } catch (error) {
    throw new ApiError(0, 'network_error', 'Network request failed; check that the backend service is running')
  }
  if (response.status === 204) {
    return undefined as T
  }
  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }
  if (!response.ok) {
    const envelope = (payload ?? {}) as ErrorEnvelope
    const err = envelope.error ?? {}
    throw new ApiError(
      response.status,
      err.code ?? 'http_error',
      err.message ?? `Request failed: HTTP ${response.status}`,
      err.details ?? null,
    )
  }
  return payload as T
}

export function jsonBody(value: unknown): BodyInit {
  return JSON.stringify(value)
}
