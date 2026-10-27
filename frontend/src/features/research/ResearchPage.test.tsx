import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Research } from '@/api/types'
import { item, research, run } from './fixtures'
import { ResearchPage } from './ResearchPage'

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })

function renderPage(r: Research, onPatch?: () => Promise<Response>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_u: string, init?: RequestInit) => (init?.method === 'PATCH' && onPatch ? onPatch() : json(r))),
  )
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/research/r1']}>
        <Routes>
          <Route path="/research/:id" element={<ResearchPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
const current = () => screen.getByRole('listitem', { current: 'step' }).textContent

class IdleES {
  addEventListener() {}
  close() {}
}
beforeEach(() => vi.stubGlobal('EventSource', IdleES))
afterEach(() => vi.unstubAllGlobals())

describe('ResearchPage step bar', () => {
  it('shows Select for a multi-item research and the title in the crumb', async () => {
    renderPage(research([item({ id: 'a' }), item({ id: 'b', name: 'Syringe' })], { title: 'Mask and syringe' }))
    expect(await screen.findByText('2 items found')).toBeInTheDocument()
    expect(current()).toContain('Select')
    expect(screen.getByText('Mask and syringe')).toBeInTheDocument()
  })

  it('has no Select step for a single item and shows Details', async () => {
    renderPage(research([item()]))
    await screen.findByRole('heading', { name: 'Details' })
    expect(screen.queryByText('Select')).toBeNull()
    expect(current()).toContain('Details')
  })

  it('shows Research and Results for run states', async () => {
    renderPage(research([item({ latest_run: run('researching') })]))
    await screen.findByRole('heading', { name: 'Researching' })
    expect(current()).toContain('Research')
  })

  it('Input is not clickable; clicking Select after Continue goes back without server writes', async () => {
    renderPage(research([item({ id: 'a' }), item({ id: 'b', name: 'Syringe' })]))
    await userEvent.click(await screen.findByRole('button', { name: 'Continue' }))
    expect(current()).toContain('Details')
    expect(screen.queryByRole('button', { name: /Input/ })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /Select/ }))
    expect(await screen.findByText('2 items found')).toBeInTheDocument()
    const calls = (fetch as ReturnType<typeof vi.fn>).mock.calls
    expect(calls.every(([, init]) => !init || init.method === 'GET')).toBe(true)
  })

  it('shows the checkbox optimistically and rolls back with the error when the PATCH fails', async () => {
    let fail!: (r: Response) => void
    const pending = new Promise<Response>((res) => (fail = res))
    renderPage(
      research([item({ id: 'a', selected: false }), item({ id: 'b', name: 'Syringe', selected: false })]),
      () => pending,
    )
    const box = await screen.findByRole('checkbox', { name: /Surgical face mask/ })
    expect(box).not.toBeChecked()
    await userEvent.click(box)
    await waitFor(() => expect(screen.getAllByRole('checkbox')[0]).toBeChecked())
    fail(json({ error: { code: 'x', message: 'Nope', details: {} } }, 500))
    expect(await screen.findByText('Nope')).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox')[0]).not.toBeChecked()
  })

  it('drops a clicked-back view when the derived step changes', async () => {
    const draft = research([item({ id: 'a' }), item({ id: 'b', name: 'Syringe' })])
    let now = draft
    vi.stubGlobal('fetch', vi.fn(async () => json(now)))
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/research/r1']}>
          <Routes>
            <Route path="/research/:id" element={<ResearchPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Continue' }))
    await userEvent.click(screen.getByRole('button', { name: /Select/ }))
    expect(await screen.findByText('2 items found')).toBeInTheDocument()
    now = research([
      item({ id: 'a', latest_run: run('queued') }),
      item({ id: 'b', name: 'Syringe', latest_run: run('queued') }),
    ])
    window.dispatchEvent(new Event('visibilitychange'))
    await screen.findByRole('heading', { name: 'Researching' })
    expect(current()).toContain('Research')
  })
})
