import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiRequest } from './client'

function mockFetch(response: Partial<Response>) {
  const fn = vi.fn().mockResolvedValue(response)
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('apiRequest', () => {
  it('parses a 2xx JSON body', async () => {
    mockFetch({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ items: [1, 2] }),
    } as Response)
    const result = await apiRequest<{ items: number[] }>('/api/v1/test')
    expect(result.items).toEqual([1, 2])
  })

  it('returns undefined for 204', async () => {
    mockFetch({ ok: true, status: 204, text: async () => '' } as Response)
    await expect(apiRequest<void>('/api/v1/test')).resolves.toBeUndefined()
  })

  it('throws ApiError with code, message and details', async () => {
    mockFetch({
      ok: false,
      status: 422,
      text: async () =>
        JSON.stringify({
          error: { code: 'validation_error', message: 'Request validation failed', details: { cron: 'invalid' } },
        }),
    } as Response)
    await expect(apiRequest('/api/v1/test')).rejects.toMatchObject({
      status: 422,
      code: 'validation_error',
      message: 'Request validation failed',
      details: { cron: 'invalid' },
    })
  })

  it('wraps network failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    const error = (await apiRequest('/api/v1/test').catch((err) => err)) as ApiError
    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('network_error')
  })
})
