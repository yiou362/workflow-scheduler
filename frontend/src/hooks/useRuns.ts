import { useQuery } from '@tanstack/react-query'
import { getLogs, getRun, getTrace, listRuns, type RunFilters } from '../api/endpoints'
import type { RunStatus } from '../api/types'

const ACTIVE_STATUSES: RunStatus[] = [
  'queued',
  'preparing',
  'submitting',
  'running',
  'waiting',
  'cancelling',
]

export function isActiveStatus(status: RunStatus | undefined): boolean {
  return status ? ACTIVE_STATUSES.includes(status) : false
}

export function useRuns(filters: RunFilters = {}) {
  return useQuery({ queryKey: ['runs', filters], queryFn: () => listRuns(filters) })
}

export function useRun(id: string | undefined) {
  return useQuery({
    queryKey: ['run', id],
    queryFn: () => getRun(id as string),
    enabled: Boolean(id),
    refetchInterval: (query) => (isActiveStatus(query.state.data?.run.status) ? 2_000 : false),
  })
}

export function useTrace(id: string | undefined, active: boolean) {
  return useQuery({
    queryKey: ['run', id, 'trace'],
    queryFn: () => getTrace(id as string),
    enabled: Boolean(id),
    refetchInterval: active ? 2_000 : false,
  })
}

export function useLogs(id: string | undefined, active: boolean) {
  return useQuery({
    queryKey: ['run', id, 'logs'],
    queryFn: () => getLogs(id as string),
    enabled: Boolean(id),
    refetchInterval: active ? 2_000 : false,
  })
}
