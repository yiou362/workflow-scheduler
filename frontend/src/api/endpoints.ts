import { apiRequest, jsonBody } from './client'
import type {
  Dashboard,
  Endpoint,
  EndpointPayload,
  EndpointTestResult,
  LogEntry,
  Meta,
  OptionsResponse,
  Page,
  PreviewResponse,
  Run,
  RunDetailResponse,
  RunListItem,
  SchedulePreviewInput,
  Task,
  TaskPayload,
  TraceResponse,
} from './types'

function query(params: Record<string, unknown>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const fetchMeta = () => apiRequest<Meta>('/api/v1/meta')
export const fetchDashboard = () => apiRequest<Dashboard>('/api/v1/dashboard')

export const listEndpoints = (params: { enabled?: boolean; page?: number; page_size?: number } = {}) =>
  apiRequest<Page<Endpoint>>(`/api/v1/endpoints${query(params)}`)
export const getEndpoint = (id: string) => apiRequest<Endpoint>(`/api/v1/endpoints/${id}`)
export const createEndpoint = (payload: EndpointPayload) =>
  apiRequest<Endpoint>('/api/v1/endpoints', { method: 'POST', body: jsonBody(payload) })
export const updateEndpoint = (id: string, payload: Partial<EndpointPayload> & { clear_password?: boolean }) =>
  apiRequest<Endpoint>(`/api/v1/endpoints/${id}`, { method: 'PUT', body: jsonBody(payload) })
export const deleteEndpoint = (id: string) =>
  apiRequest<void>(`/api/v1/endpoints/${id}`, { method: 'DELETE' })
export const setDefaultEndpoint = (id: string) =>
  apiRequest<Endpoint>(`/api/v1/endpoints/${id}/default`, { method: 'POST' })
export const enableEndpoint = (id: string) =>
  apiRequest<Endpoint>(`/api/v1/endpoints/${id}/enable`, { method: 'POST' })
export const disableEndpoint = (id: string) =>
  apiRequest<Endpoint>(`/api/v1/endpoints/${id}/disable`, { method: 'POST' })
export const testEndpoint = (payload: {
  endpoint_id?: string
  base_url?: string
  auth_type?: 'none' | 'basic'
  auth_username?: string | null
  password?: string | null
}) =>
  apiRequest<EndpointTestResult>('/api/v1/endpoints/test', {
    method: 'POST',
    body: jsonBody(payload),
  })

export interface TaskFilters {
  status?: string
  endpoint_id?: string
  schedule_type?: string
  last_status?: string
  tag?: string
  page?: number
  page_size?: number
}

export const listTasks = (filters: TaskFilters = {}) =>
  apiRequest<Page<Task>>(`/api/v1/tasks${query({ ...filters })}`)
export const getTask = (id: string) => apiRequest<Task>(`/api/v1/tasks/${id}`)
export const createTask = (payload: TaskPayload) =>
  apiRequest<Task>('/api/v1/tasks', { method: 'POST', body: jsonBody(payload) })
export const updateTask = (id: string, payload: TaskPayload) =>
  apiRequest<Task>(`/api/v1/tasks/${id}`, { method: 'PUT', body: jsonBody(payload) })
export const copyTask = (id: string) =>
  apiRequest<Task>(`/api/v1/tasks/${id}/copy`, { method: 'POST' })
export const enableTask = (id: string) =>
  apiRequest<Task>(`/api/v1/tasks/${id}/enable`, { method: 'POST' })
export const disableTask = (id: string) =>
  apiRequest<Task>(`/api/v1/tasks/${id}/disable`, { method: 'POST' })
export const archiveTask = (id: string) =>
  apiRequest<Task>(`/api/v1/tasks/${id}/archive`, { method: 'POST' })
export const restoreTask = (id: string) =>
  apiRequest<Task>(`/api/v1/tasks/${id}/restore`, { method: 'POST' })
export const runTaskNow = (id: string) =>
  apiRequest<{ run: Run; message: string }>(`/api/v1/tasks/${id}/run`, { method: 'POST' })
export const previewSchedule = (payload: SchedulePreviewInput) =>
  apiRequest<PreviewResponse>('/api/v1/schedules/preview', {
    method: 'POST',
    body: jsonBody(payload),
  })
export const fetchOptions = (endpointId: string, workingDirectory: string) =>
  apiRequest<OptionsResponse>(
    `/api/v1/options${query({ endpoint_id: endpointId, working_directory: workingDirectory })}`,
  )

export interface RunFilters {
  task_id?: string
  endpoint_id?: string
  status?: string
  source?: string
  from?: string
  to?: string
  model?: string
  page?: number
  page_size?: number
}

export const listRuns = (filters: RunFilters = {}) =>
  apiRequest<Page<RunListItem>>(`/api/v1/runs${query({ ...filters })}`)
export const getRun = (id: string) => apiRequest<RunDetailResponse>(`/api/v1/runs/${id}`)
export const getTrace = (id: string) => apiRequest<TraceResponse>(`/api/v1/runs/${id}/trace`)
export const getLogs = (id: string) => apiRequest<{ items: LogEntry[] }>(`/api/v1/runs/${id}/logs`)
export const cancelRun = (id: string) =>
  apiRequest<{ status: string; message: string }>(`/api/v1/runs/${id}/cancel`, { method: 'POST' })
export const rerunRun = (id: string, endpointId?: string) =>
  apiRequest<{ run: Run; message: string }>(`/api/v1/runs/${id}/rerun`, {
    method: 'POST',
    body: jsonBody({ endpoint_id: endpointId ?? null }),
  })
export const replyPermission = (
  runId: string,
  requestId: string,
  decision: 'once' | 'always' | 'reject',
  message?: string,
) =>
  apiRequest<void>(`/api/v1/runs/${runId}/permissions/${requestId}/reply`, {
    method: 'POST',
    body: jsonBody({ decision, message: message ?? null }),
  })
