import { useQuery } from '@tanstack/react-query'
import { fetchMeta } from '../api/endpoints'

export function useMeta() {
  return useQuery({ queryKey: ['meta'], queryFn: fetchMeta, staleTime: 60_000 })
}
