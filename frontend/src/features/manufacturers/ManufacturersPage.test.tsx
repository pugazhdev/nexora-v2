import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Manufacturer } from '@/api/types'
import { ManufacturersPage } from './ManufacturersPage'

afterEach(() => vi.unstubAllGlobals())
const m = (o: Partial<Manufacturer> = {}): Manufacturer => ({
  id: 'm1', name: 'Acme Medical', city: 'Pune', state: 'MH', website: null,
  platforms: ['IndiaMART', 'TradeIndia'], listing_count: 4, last_seen: '2026-10-20T00:00:00Z', starred: false, confirmed: true, ...o,
})
const json = (b: unknown) => new Response(JSON.stringify(b))
function Probe() {
  useQuery({ queryKey: ['manufacturers'], queryFn: () => fetch('/api/manufacturers').then((r) => r.json()) })
  return null
}
const setup = (f: unknown, starred = false) => {
  vi.stubGlobal('fetch', f)
  const qc = new QueryClient()
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Probe />
        <ManufacturersPage starred={starred} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return qc
}

describe('ManufacturersPage', () => {
  it('lists rows; star calls PATCH and invalidates every manufacturers query', async () => {
    let calls = 0
    const f = vi.fn(async (_u: string, init?: RequestInit) => {
      if (init?.method === 'PATCH') return json(m({ starred: true }))
      calls++
      return json([m()])
    })
    setup(f)
    expect(await screen.findByText('Acme Medical')).toBeInTheDocument()
    expect(screen.getByText('IndiaMART, TradeIndia')).toBeInTheDocument()
    const before = calls
    await userEvent.click(screen.getByRole('button', { name: 'Star Acme Medical' }))
    expect(f).toHaveBeenCalledWith('/api/manufacturers/m1', expect.objectContaining({ method: 'PATCH', body: '{"starred":true}' }))
    await waitFor(() => expect(calls).toBeGreaterThanOrEqual(before + 2)) // directory + probe refetched
  })

  it('tags an unconfirmed maker (I4)', async () => {
    setup(vi.fn(async () => json([m(), m({ id: 'm2', name: 'Zed Traders', confirmed: false })])))
    expect(await screen.findByText('Zed Traders')).toBeInTheDocument()
    expect(screen.getAllByText('Unconfirmed')).toHaveLength(1)
    expect(screen.getByText('Unconfirmed').closest('td')).toHaveTextContent('Zed Traders')
  })

  it('search sends debounced ?q=', async () => {
    const f = vi.fn(async () => json([]))
    setup(f)
    await userEvent.type(await screen.findByRole('searchbox'), 'ac')
    await waitFor(() => expect(f).toHaveBeenCalledWith('/api/manufacturers?q=ac&limit=50&offset=0', expect.anything()))
    expect(f).not.toHaveBeenCalledWith('/api/manufacturers?q=a&limit=50&offset=0', expect.anything())
  })

  it('shortlist filters starred and has its own copy', async () => {
    const f = vi.fn(async () => json([]))
    setup(f, true)
    expect(await screen.findByText('No starred manufacturers yet.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Shortlist' })).toBeInTheDocument()
    expect(f).toHaveBeenCalledWith('/api/manufacturers?starred=true&limit=50&offset=0', expect.anything())
  })
})

describe('ManufacturersPage paging', () => {
  it('Load more fetches next page and dedupes by id', async () => {
    const full = Array.from({ length: 50 }, (_, i) => m({ id: `m${i}`, name: `Maker ${i}` }))
    const f = vi.fn(async (u: string) => json(u.includes('offset=50') ? [full[0], m({ id: 'x', name: 'Last one' })] : full))
    setup(f)
    await userEvent.click(await screen.findByRole('button', { name: 'Load more' }))
    expect(await screen.findByText('Last one')).toBeInTheDocument()
    expect(screen.getAllByText('Maker 0')).toHaveLength(1)
    expect(f).toHaveBeenCalledWith('/api/manufacturers?limit=50&offset=50', expect.anything())
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull()
  })
})
