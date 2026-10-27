import { afterEach, expect, it, vi } from 'vitest'
import { api, ApiError } from './client'

afterEach(() => vi.unstubAllGlobals())

it('maps an error JSON body to ApiError', async () => {
  const body = { error: { code: 'not_found', message: 'Item not found.', details: { id: 'x' } } }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 404 })))
  const err = await api.get('/research/x').catch((e) => e)
  expect(err).toBeInstanceOf(ApiError)
  expect(err).toMatchObject({ code: 'not_found', message: 'Item not found.', details: { id: 'x' }, status: 404 })
})

it('maps a network failure to code network', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
  const err = await api.post('/research', { a: 1 }).catch((e) => e)
  expect(err).toBeInstanceOf(ApiError)
  expect(err).toMatchObject({ code: 'network', status: 0 })
})

it('sends JSON bodies and returns parsed JSON', async () => {
  const f = vi.fn().mockResolvedValue(new Response('{"ok":true}', { status: 200 }))
  vi.stubGlobal('fetch', f)
  expect(await api.patch('/x', { selected: true })).toEqual({ ok: true })
  const [url, init] = f.mock.calls[0]!
  expect(url).toBe('/api/x')
  expect(init).toMatchObject({ method: 'PATCH', body: '{"selected":true}' })
})
