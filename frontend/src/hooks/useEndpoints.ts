import { useQuery } from '@tanstack/react-query'
import { getEndpoint, listEndpoints } from '../api/endpoints'

export function useEndpoints(enabled?: boolean) {
  return useQuery({
    queryKey: ['endpoints', { enabled }],
    queryFn: () => listEndpoints({ enabled, page_size: 200 }),
  })
}

export function useEndpoint(id: string | undefined) {
  return useQuery({
    queryKey: ['endpoint', id],
    queryFn: () => getEndpoint(id as string),
    enabled: Boolean(id),
  })
}
