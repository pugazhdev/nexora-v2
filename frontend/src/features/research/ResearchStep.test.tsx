import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Research } from '@/api/types'
import { item, research, run } from './fixtures'
import { ResearchStep } from './ResearchStep'

class FakeES {
  static all: FakeES[] = []
  readyState = 1
  closed = false
  handlers: Record<string, ((e: MessageEvent) => void)[]> = {}
  onerror: (() => void) | null = null
  url: string
  constructor(url: string) {
    this.url = url
    FakeES.all.push(this)
  }
  addEventListener(t: string, h: (e: MessageEvent) => void) {
    ;(this.handlers[t] ??= []).push(h)
  }
  close() {
    this.closed = true
    this.readyState = 2
  }
  emit(t: string, data: unknown, id = '') {
    act(() => this.handlers[t]?.forEach((h) => h({ data: JSON.stringify(data), lastEventId: id } as MessageEvent)))
  }
}
const last = () => FakeES.all[FakeES.all.length - 1]!
const ev = (id: number, item_id: string, message: string, level = 'info') => ({
  id, run_id: 'r', item_id, at: '2026-10-26T00:00:00Z', phase: 'search', level, message,
})
const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 })

const live: Research = research([
  item({ id: 'a', name: 'Mask', latest_run: run('done') }),
  item({ id: 'b', name: 'Syringe', latest_run: run('researching') }),
  item({ id: 'c', name: 'Gloves', latest_run: run('queued') }),
])

function setup(r: Research) {
  const fetchMock = vi.fn(async () => json({}))
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('EventSource', FakeES)
  FakeES.all = []
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  qc.setQueryData(['research', 'r1'], r)
  const spy = vi.spyOn(qc, 'invalidateQueries')
  render(
    <QueryClientProvider client={qc}>
      <ResearchStep research={r} />
    </QueryClientProvider>,
  )
  return { fetchMock, spy }
}
afterEach(() => vi.unstubAllGlobals())

describe('ResearchStep', () => {
  it('opens the stream from 0, renders steps of the running item in order, dedupes by id', () => {
    setup(live)
    expect(last().url).toBe('/api/research/r1/events?after=0')
    last().emit('step', ev(1, 'b', 'Searched 6 queries'), '1')
    last().emit('step', ev(2, 'b', 'Found 23 listings'), '2')
    last().emit('step', ev(2, 'b', 'Found 23 listings'), '2')
    last().emit('step', { ...ev(3, 'a', 'Other item line'), run_id: 'other' }, '3')
    const lines = screen.getAllByText(/Searched|Found/).map((e) => e.textContent)
    expect(lines).toEqual(['Searched 6 queries', 'Found 23 listings'])
    expect(screen.queryByText('Other item line')).toBeNull()
    expect(screen.getByText('2 of 3')).toBeInTheDocument()
    expect(screen.getByText(/You can leave this page/)).toBeInTheDocument()
  })

  it('refetches on status; closes on all terminal', () => {
    const { spy } = setup(live)
    last().emit('status', { status: 'researching', items: [{ item_id: 'b', run_id: 'r', status: 'researching', error: null }] })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['research', 'r1'] })
    expect(last().closed).toBe(false)
    last().emit('status', { status: 'done', items: [{ item_id: 'b', run_id: 'r', status: 'done', error: null }] })
    expect(last().closed).toBe(true)
  })

  it('interrupted item shows message and Retry posts', async () => {
    const r = research([item({ id: 'b', name: 'Syringe', latest_run: { ...run('interrupted'), error: null } })])
    const { fetchMock } = setup(r)
    expect(screen.getByText('Interrupted by a server restart')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/items/b/retry', expect.objectContaining({ method: 'POST' })),
    )
  })

  it('failed shows run error; cancel posts', async () => {
    const r = research([
      item({ id: 'a', latest_run: { ...run('failed'), error: 'No listings found' } }),
      item({ id: 'b', name: 'Syringe', latest_run: run('researching') }),
    ])
    const { fetchMock } = setup(r)
    expect(screen.getByText('No listings found')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/research/r1/cancel', expect.objectContaining({ method: 'POST' })),
    )
  })

  it('progress counts terminal items plus a capped fraction', () => {
    setup(live)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '33')
    for (let i = 1; i <= 50; i++) last().emit('step', ev(i, 'b', `s${i}`), String(i))
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '63')
  })

  it('resumes with the last id after the stream errors closed', () => {
    setup(live)
    last().emit('step', ev(7, 'b', 'x'), '7')
    last().readyState = 2
    act(() => last().onerror?.())
    expect(FakeES.all).toHaveLength(2)
    expect(last().url).toBe('/api/research/r1/events?after=7')
  })
})

describe('ResearchStep fixes', () => {
  const rerun = (r: Research) => {
    const qc = new QueryClient()
    const ui = (x: Research) => (
      <QueryClientProvider client={qc}>
        <ResearchStep research={x} />
      </QueryClientProvider>
    )
    const v = render(ui(r))
    return (x: Research) => v.rerender(ui(x))
  }
  it('retry keeps the bar from decreasing and logs only the new attempt', () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({})))
    vi.stubGlobal('EventSource', FakeES)
    FakeES.all = []
    const mk = (status: 'done' | 'researching', id: string) =>
      research([item({ id: 'a', name: 'Mask', latest_run: { ...run(status), id } }), item({ id: 'b', name: 'Syringe', latest_run: run('done') })])
    const update = rerun(mk('done', 'r1'))
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
    last().emit('step', { ...ev(1, 'a', 'old attempt'), run_id: 'r1' }, '1')
    update(mk('researching', 'r2'))
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
    last().emit('step', { ...ev(2, 'a', 'new attempt'), run_id: 'r2' }, '2')
    expect(screen.queryByText('old attempt')).toBeNull()
    expect(screen.getByText('new attempt')).toBeInTheDocument()
    expect(screen.getByRole('log')).toBeInTheDocument()
  })
  it('shows cancel and retry errors', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ error: { code: 'x', message: 'Nope' } }), { status: 500 }))
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('EventSource', FakeES)
    const r = research([
      item({ id: 'a', latest_run: run('interrupted') }),
      item({ id: 'b', name: 'Syringe', latest_run: run('researching') }),
    ])
    rerun(r)
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Nope')
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.getAllByRole('alert')).toHaveLength(2))
  })
})
