export type RunStatus =
  | 'queued'
  | 'preparing'
  | 'submitting'
  | 'running'
  | 'waiting'
  | 'completed'
  | 'failed'
  | 'cancelling'
  | 'cancelled'
  | 'timeout'
  | 'skipped'
  | 'unknown'

export type TaskStatus = 'enabled' | 'disabled' | 'archived'
export type ScheduleType = 'none' | 'cron' | 'once' | 'interval'
export type TriggerSource = 'scheduled' | 'manual' | 'rerun' | 'recovery'
export type TraceIntegrity = 'complete' | 'gap' | 'incomplete' | 'none'

export interface Meta {
  version: string
  server_time: string
  utc_offset: string
  utc_offset_label: string
  frontend_version: string | null
}

export interface Endpoint {
  id: string
  name: string
  description: string | null
  base_url: string
  auth_type: 'none' | 'basic'
  auth_username: string | null
  has_password: boolean
  is_default: boolean
  enabled: boolean
  task_count: number
  last_test_at: string | null
  last_test_result: string | null
  last_test_message: string | null
  last_test_version: string | null
  created_at: string
  updated_at: string
}

export interface EndpointPayload {
  name: string
  description?: string | null
  base_url: string
  auth_type: 'none' | 'basic'
  auth_username?: string | null
  password?: string | null
  enabled?: boolean
  is_default?: boolean
}

export interface EndpointTestResult {
  result: 'success' | 'unreachable' | 'auth_failed' | 'unsupported' | 'service_error' | 'timeout'
  message: string
  version: string | null
  tested_at: string
}

export interface Task {
  id: string
  name: string
  description: string | null
  tags: string[]
  endpoint_id: string
  endpoint_name: string | null
  working_directory: string
  provider_id: string
  model_id: string
  model_variant: string | null
  agent: string | null
  prompt: string
  status: TaskStatus
  schedule_enabled: boolean
  schedule_type: ScheduleType
  cron_expression: string | null
  run_at: string | null
  interval_seconds: number | null
  overlap_policy: 'queue' | 'skip'
  missed_policy: 'skip' | 'run_once'
  timeout_minutes: number
  next_run_at: string | null
  schedule_summary: string
  created_at: string
  updated_at: string
  archived_at: string | null
  last_run: RunBrief | null
}

export interface TaskPayload {
  name: string
  description?: string | null
  tags: string[]
  endpoint_id: string
  working_directory: string
  provider_id: string
  model_id: string
  model_variant?: string | null
  agent?: string | null
  prompt: string
  status: 'enabled' | 'disabled'
  schedule_enabled: boolean
  schedule_type: ScheduleType
  cron_expression?: string | null
  run_at?: string | null
  interval_seconds?: number | null
  overlap_policy: 'queue' | 'skip'
  missed_policy: 'skip' | 'run_once'
  timeout_minutes: number
}

export interface RunBrief {
  id: string
  status: RunStatus
  trigger_source: TriggerSource
  started_at: string | null
  finished_at: string | null
  created_at: string
  duration_ms: number | null
}

export interface RunUsage {
  input_tokens: number | null
  output_tokens: number | null
  reasoning_tokens: number | null
  cache_read_tokens: number | null
  cache_write_tokens: number | null
  cost_usd: number | null
}

export interface Run {
  id: string
  task_id: string
  task_name: string
  status: RunStatus
  trigger_source: TriggerSource
  scheduled_for: string | null
  created_at: string
  queued_at: string | null
  started_at: string | null
  submitting_at: string | null
  running_at: string | null
  finished_at: string | null
  deadline_at: string | null
  cancel_requested_at: string | null
  cancel_confirmed_at: string | null
  cancel_reason: string | null
  duration_ms: number | null
  queue_wait_ms: number | null
  endpoint: { id: string | null; name: string; base_url: string; auth_type: string }
  working_directory: string
  provider_id: string
  model_id: string
  model_variant: string | null
  agent: string | null
  prompt: string
  utc_offset: string
  schedule_summary: string
  overlap_policy: 'queue' | 'skip'
  missed_policy: 'skip' | 'run_once'
  timeout_minutes: number
  opencode_session_id: string | null
  opencode_session_title: string | null
  final_response: string | null
  final_response_truncated: boolean
  error_phase: string | null
  error_type: string | null
  error_message: string | null
  trace_integrity: TraceIntegrity | null
  trace_gap_count: number
  usage: RunUsage
  rerun_of_run_id: string | null
  config_snapshot: Record<string, unknown>
}

export interface RunListItem {
  id: string
  task_id: string
  task_name: string
  status: RunStatus
  trigger_source: TriggerSource
  endpoint_id: string | null
  endpoint_name: string
  model_id: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  trace_integrity: TraceIntegrity | null
  utc_offset: string
  error_type: string | null
}

export interface PendingPermission {
  request_id: string
  action: string
  status: string
  requested_at: string
  input: unknown
  metadata: Record<string, unknown> | null
}

export interface RunDetailResponse {
  run: Run
  pending_permissions: PendingPermission[]
}

export interface TraceItem {
  id: string
  kind: 'user_message' | 'assistant_message' | 'tool' | 'skill' | 'file' | 'permission' | 'error' | 'system'
  external_id: string
  parent_external_id: string | null
  name: string | null
  status: string | null
  sequence: number
  started_at: string | null
  ended_at: string | null
  duration_ms: number | null
  input: unknown
  output: string | null
  error: string | null
  metadata: Record<string, unknown> | null
}

export interface TraceResponse {
  items: TraceItem[]
  integrity: TraceIntegrity | null
  gap_count: number
  view: string
}

export interface LogEntry {
  id: string
  at: string
  level: string
  phase: string
  message: string
  details: Record<string, unknown> | null
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Dashboard {
  endpoints: {
    total: number
    enabled: number
    disabled: number
    default: Endpoint | null
    items: Endpoint[]
  }
  tasks: { total: number; enabled: number; disabled: number; archived: number }
  runs: {
    queued: number
    preparing: number
    submitting: number
    running: number
    waiting: number
    cancelling: number
    failed_30d: number
    completed_30d: number
  }
  upcoming: {
    task_id: string
    task_name: string
    endpoint_id: string
    next_run_at: string
    schedule_summary: string
  }[]
  recent_runs: RunListItem[]
  recent_failures: RunListItem[]
}

export interface ModelOption {
  provider_id: string
  model_id: string
  name: string | null
  variants: string[]
}

export interface AgentOption {
  id: string
  name: string | null
  description: string | null
  mode: string | null
}

export interface OptionsResponse {
  models: ModelOption[]
  agents: AgentOption[]
  warning: string | null
}

export interface PreviewOccurrence {
  utc: string
  local: string
}

export interface PreviewResponse {
  occurrences: PreviewOccurrence[]
  utc_offset: string
  utc_offset_label: string
}

export interface SchedulePreviewInput {
  type: ScheduleType
  cron?: string | null
  run_at?: string | null
  interval_seconds?: number | null
  count?: number
}
