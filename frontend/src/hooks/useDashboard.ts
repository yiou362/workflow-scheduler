import { useQuery } from '@tanstack/react-query'
import { fetchDashboard } from '../api/endpoints'

export function useDashboard() {
  return useQuery({ queryKey: ['dashboard'], queryFn: fetchDashboard, refetchInterval: 5_000 })
}
