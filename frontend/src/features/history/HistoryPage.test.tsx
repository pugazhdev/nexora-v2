import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HistoryPage } from './HistoryPage'

afterEach(() => vi.unstubAllGlobals())
const row = (i: number) => ({ id: `r${i}`, title: `Study ${i}`, created_at: '2026-10-26T10:30:00Z', status: 'done' })
const setup = (f: unknown) => {
  vi.stubGlobal('fetch', f)
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<HistoryPage />} />
          <Route path="/research/:id" element={<p>opened</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('HistoryPage', () => {
  it('row link opens the research', async () => {
    setup(vi.fn(async () => new Response(JSON.stringify([row(1)]))))
    const link = await screen.findByRole('link', { name: 'Study 1' })
    expect(link).toHaveAttribute('href', '/research/r1')
    await userEvent.click(link)
    expect(screen.getByText('opened')).toBeInTheDocument()
  })

  it('empty state', async () => {
    setup(vi.fn(async () => new Response('[]')))
    expect(await screen.findByText('No research yet. Start one from New research.')).toBeInTheDocument()
  })

  it('Load more fetches the next page, hidden on a short page', async () => {
    const full = Array.from({ length: 50 }, (_, i) => row(i))
    const f = vi.fn(async (u: string) => new Response(JSON.stringify(u.includes('offset=50') ? [row(99)] : full)))
    setup(f)
    await userEvent.click(await screen.findByRole('button', { name: 'Load more' }))
    expect(await screen.findByRole('link', { name: 'Study 99' })).toBeInTheDocument()
    expect(f).toHaveBeenCalledWith('/api/research?limit=50&offset=50', expect.anything())
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull()
  })
})

describe('HistoryPage details', () => {
  it('shows item count and dedupes rows across pages', async () => {
    const full = Array.from({ length: 50 }, (_, i) => ({ ...row(i), item_count: 3 }))
    setup(vi.fn(async (u: string) => new Response(JSON.stringify(u.includes('offset=50') ? [full[0]] : full))))
    await userEvent.click(await screen.findByRole('button', { name: 'Load more' }))
    await screen.findByRole('columnheader', { name: 'Items' })
    expect(screen.getAllByRole('link', { name: 'Study 0' })).toHaveLength(1)
    expect(screen.getAllByText('3').length).toBe(50)
  })
})

describe('HistoryPage delete', () => {
  it('trash then confirm calls DELETE; the row can be cancelled', async () => {
    const f = vi.fn(async (_u: string, init?: RequestInit) =>
      init?.method === 'DELETE' ? new Response(null, { status: 204 }) : new Response(JSON.stringify([row(1)])),
    )
    setup(f)
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Study 1' }))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.getByRole('link', { name: 'Study 1' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Delete Study 1' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(f).toHaveBeenCalledWith('/api/research/r1', expect.objectContaining({ method: 'DELETE' }))
  })
})
