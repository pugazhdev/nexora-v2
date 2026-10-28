import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ItemRun } from '@/api/types'
import { item, research } from '../research/fixtures'
import { offer, result } from './fixtures'
import { ResultsStep } from './ResultsStep'

const mk = (o: Partial<ItemRun>) =>
  ({
    id: 'r',
    status: 'done',
    result: result({ offers: [offer('a')] }),
    error: null,
    split_status: null,
    ...o,
  }) as ItemRun
afterEach(() => vi.unstubAllGlobals())

describe('ResultsStep', () => {
  it('tabs per item; units prefilled from answers; failed tab offers Retry', async () => {
    const f = vi.fn(async () => new Response('{}'))
    vi.stubGlobal('fetch', f)
    const r = research([
      item({ id: 'a', name: 'Mask', answers: { quantity: 50, unit_basis: 1000 }, latest_run: mk({}) }),
      item({ id: 'b', name: 'Syringe', latest_run: mk({ status: 'failed', result: null, error: 'Boom' }) }),
    ])
    render(
      <QueryClientProvider client={new QueryClient()}><MemoryRouter>
        <ResultsStep research={r} />
      </MemoryRouter></QueryClientProvider>,
    )
    expect(screen.getByText('Manufacturing cost')).toBeInTheDocument()
    expect(screen.getByLabelText('Units')).toHaveValue('50,000')
    await userEvent.click(screen.getByRole('tab', { name: /Syringe/ }))
    expect(screen.queryByText('Manufacturing cost')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(f).toHaveBeenCalledWith('/api/items/b/retry', expect.objectContaining({ method: 'POST' }))
  })
})

describe('ResultsStep earlier runs', () => {
  const old = mk({ id: 'old', result: result({ offers: [offer('a')], spec_title: 'Old spec', quantity: 777 }) })
  const body = (u: string) =>
    u === '/api/items/a/runs'
      ? [
          { id: 'new', status: 'done', started_at: '2026-10-26T10:00:00Z', finished_at: null },
          { id: 'old', status: 'failed', started_at: '2026-10-25T10:00:00Z', finished_at: null },
        ]
      : u === '/api/runs/old'
        ? { ...old, item_id: 'a' }
        : {}
  const show = (url: string) => {
    vi.stubGlobal('fetch', vi.fn(async (u: string) => new Response(JSON.stringify(body(u)))))
    const r = research([
      item({
        id: 'a',
        name: 'Mask',
        splittable: true,
        parts: [{ name: 'Body', typical_material: 'PP', count_per_unit: 1 }],
        answers: { quantity: 50 },
        latest_run: mk({ id: 'new' }),
      }),
    ])
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={[url]}>
          <ResultsStep research={r} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  it('select loads an earlier run read-only; Back to latest returns', async () => {
    show('/research/r1')
    expect(screen.getByRole('button', { name: /Split and research/ })).toBeInTheDocument()
    await userEvent.selectOptions(await screen.findByLabelText('Earlier runs'), 'old')
    expect(await screen.findByText('Viewing an earlier run')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Split and research/ })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
    await userEvent.click(screen.getByRole('link', { name: 'Back to latest' }))
    expect(screen.queryByText('Viewing an earlier run')).toBeNull()
  })

  it('deep link ?run= opens it', async () => {
    show('/research/r1?run=old')
    expect(await screen.findByText('Viewing an earlier run')).toBeInTheDocument()
  })

  it('no select when the item has one run', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify([{ id: 'new', status: 'done' }]))))
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <ResultsStep research={research([item({ id: 'a', latest_run: mk({ id: 'new' }) })])} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await screen.findByText('Manufacturing cost')
    expect(screen.queryByLabelText('Earlier runs')).toBeNull()
  })
})

describe('ResultsStep earlier run edge cases', () => {
  const rows = (status: string) => [
    { id: 'new', status: 'done', started_at: '2026-10-26T10:00:00Z', finished_at: null },
    { id: 'old', status, started_at: '2026-10-25T10:00:00Z', finished_at: null },
  ]
  const go = (url: string, runs: unknown, run: unknown = {}) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (u: string) => new Response(JSON.stringify(u.startsWith('/api/items/') ? runs : u.startsWith('/api/runs/') ? run : {}))),
    )
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={[url]}>
          <ResultsStep research={research([item({ id: 'a', latest_run: mk({ id: 'new' }) })])} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }
  it('labels a running earlier run with its real status', async () => {
    go('/x', rows('researching'))
    expect(await screen.findByRole('option', { name: /Running/ })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Done/ })).toBeNull()
  })
  it('ignores ?run= pointing at the latest run', async () => {
    go('/x?run=new', rows('done'), { ...mk({ id: 'new' }), item_id: 'a' })
    await screen.findByText('Manufacturing cost')
    expect(screen.queryByText('Viewing an earlier run')).toBeNull()
  })
  it('ignores ?run= for a run of another item', async () => {
    go('/x?run=zzz', rows('done'), { ...mk({ id: 'zzz' }), item_id: 'other' })
    await screen.findByText('Manufacturing cost')
    expect(screen.queryByText('Viewing an earlier run')).toBeNull()
  })
})

describe('ResultsStep retail section', () => {
  const retail = (title: string) => ({
    rows: [
      { retailer: 'Tata 1mg', title, url: 'https://www.1mg.com/p', pack_size: 10, unit_price: '15.00',
        pack_price: '150.00', price_quote: '₹150' },
    ],
    notes: [],
    queries: [],
  })
  const show = (url: string, latest: Partial<ItemRun>, old?: ItemRun) => {
    const body = (u: string) =>
      u === '/api/items/a/runs'
        ? [
            { id: 'new', status: latest.status ?? 'done', started_at: '2026-10-26T10:00:00Z', finished_at: null },
            { id: 'old', status: 'done', started_at: '2026-10-25T10:00:00Z', finished_at: null },
          ]
        : u === '/api/runs/old'
          ? { ...old, item_id: 'a' }
          : {}
    vi.stubGlobal('fetch', vi.fn(async (u: string) => new Response(JSON.stringify(body(u)))))
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={[url]}>
          <ResultsStep research={research([item({ id: 'a', latest_run: mk({ id: 'new', ...latest }) })])} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  it('latest run shows the retail rows', async () => {
    show('/x', { retail: retail('Latest syringe') })
    expect(screen.getByRole('heading', { name: 'Retail price' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Latest syringe' })).toHaveAttribute('href', 'https://www.1mg.com/p')
  })

  it('an earlier run shows its own retail rows read-only', async () => {
    show('/x?run=old', { retail: retail('Latest syringe') }, mk({ id: 'old', retail: retail('Old syringe') }))
    expect(await screen.findByText('Viewing an earlier run')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Old syringe' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Latest syringe' })).toBeNull()
  })

  it('a researching item shows the retail spinner line', () => {
    show('/x', { status: 'researching', result: null, retail: null })
    expect(screen.getByText('Finding retail prices...')).toBeInTheDocument()
  })
})
