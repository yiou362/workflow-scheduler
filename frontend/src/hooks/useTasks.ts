import { useQuery } from '@tanstack/react-query'
import { getTask, listTasks, type TaskFilters } from '../api/endpoints'

export function useTasks(filters: TaskFilters = {}) {
  return useQuery({
    queryKey: ['tasks', filters],
    queryFn: () => listTasks(filters),
    refetchInterval: 5_000,
  })
}

export function useTask(id: string | undefined) {
  return useQuery({
    queryKey: ['task', id],
    queryFn: () => getTask(id as string),
    enabled: Boolean(id),
  })
}
