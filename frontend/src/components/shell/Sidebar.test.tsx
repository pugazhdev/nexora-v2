import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useQuery } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Sidebar } from './Sidebar'

const day = 86400000
const ago = (d: number) => new Date(Date.now() - d * day).toISOString()

function mockApi() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const body = url === '/api/manufacturers/count'
        ? { total: 120, starred: 7 }
        : url.startsWith('/api/research')
        ? [
            { id: 'a', title: 'Nitrile gloves', created_at: ago(0), status: 'researching' },
            { id: 'b', title: 'IV cannula', created_at: ago(3), status: 'done' },
            { id: 'c', title: 'Ancient thing', created_at: ago(30), status: 'done' },
          ]
        : [
            { id: 'm1', starred: true },
            { id: 'm2', starred: false },
            { id: 'm3', starred: false },
          ]
      return new Response(JSON.stringify(body), { status: 200 })
    }),
  )
}

function renderAt(path: string) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Sidebar />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('Sidebar', () => {
  it('groups recent research into Today and This week and drops older ones', async () => {
    mockApi()
    renderAt('/')
    const today = (await screen.findByText('Today')).parentElement!
    expect(within(today).getByText('Nitrile gloves')).toBeInTheDocument()
    expect(within(today).queryByText('IV cannula')).toBeNull()
    const week = screen.getByText('This week').parentElement!
    expect(within(week).getByText('IV cannula')).toBeInTheDocument()
    expect(screen.queryByText('Ancient thing')).toBeNull()
  })

  it('shows counts and a pulsing dot only for researching items', async () => {
    mockApi()
    renderAt('/')
    expect(await screen.findByRole('link', { name: /Manufacturers\s*120/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Shortlist\s*7/ })).toBeInTheDocument()
    expect(screen.getByText('Nitrile gloves').querySelector('.dot-run')).not.toBeNull()
    expect(screen.getByText('IV cannula').querySelector('.dot-run')).toBeNull()
  })

  it('highlights the active route with aria-current', async () => {
    mockApi()
    renderAt('/manufacturers')
    expect(screen.getByRole('link', { name: /Manufacturers/ })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: /History/ })).not.toHaveAttribute('aria-current')
    await screen.findByText('Today')
  })

  it('shows an error with Retry when recent research fails, then recovers', async () => {
    mockApi()
    const ok = globalThis.fetch as unknown as (u: string) => Promise<Response>
    let fail = true
    vi.stubGlobal(
      'fetch',
      vi.fn(async (u: string) => {
        if (fail && u.startsWith('/api/research')) throw new Error('down')
        return ok(u)
      }),
    )
    renderAt('/')
    expect(await screen.findByText(/Could not load recent research/)).toBeInTheDocument()
    fail = false
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(screen.getByText('Today')).toBeInTheDocument())
    expect(screen.queryByText(/Could not load/)).toBeNull()
  })

  it('highlights the open research', async () => {
    mockApi()
    renderAt('/research/b')
    expect(await screen.findByRole('link', { name: /IV cannula/ })).toHaveAttribute('aria-current', 'page')
  })
})

describe('Sidebar delete', () => {
  function deleteApi(status = 204, message = 'Cancel the research before deleting it.') {
    mockApi()
    const base = globalThis.fetch as unknown as (u: string, i?: RequestInit) => Promise<Response>
    const f = vi.fn(async (u: string, init?: RequestInit) => {
      if (init?.method === 'DELETE') {
        return status === 204
          ? new Response(null, { status })
          : new Response(JSON.stringify({ error: { code: 'conflict', message, details: {} } }), { status })
      }
      return base(u, init)
    })
    vi.stubGlobal('fetch', f)
    return f
  }
  const deletes = (f: ReturnType<typeof vi.fn>) => f.mock.calls.filter((c) => c[1]?.method === 'DELETE')

  function renderWithClient(path: string) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <Sidebar />
          <Routes>
            <Route path="/" element={<p>home</p>} />
            <Route path="/research/:id" element={<p>research page</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    return invalidate
  }

  it('confirm calls DELETE then invalidates research and manufacturers', async () => {
    const f = deleteApi()
    const invalidate = renderWithClient('/')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Nitrile gloves' }))
    expect(screen.getByText('Delete?')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(deletes(f)).toHaveLength(1))
    expect(deletes(f)[0]?.[0]).toBe('/api/research/a')
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['research'] })
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['manufacturers'] })
    })
  })

  it('cancel does nothing', async () => {
    const f = deleteApi()
    renderWithClient('/')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Nitrile gloves' }))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(deletes(f)).toHaveLength(0)
    expect(screen.getByRole('link', { name: /Nitrile gloves/ })).toBeInTheDocument()
  })

  it('deleting the open research navigates home', async () => {
    deleteApi()
    renderWithClient('/research/a')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Nitrile gloves' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(await screen.findByText('home')).toBeInTheDocument()
  })

  it('deleting another research stays on the page', async () => {
    const f = deleteApi()
    renderWithClient('/research/a')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete IV cannula' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(deletes(f)).toHaveLength(1))
    expect(screen.queryByText('home')).toBeNull()
  })

  it('does not refetch the deleted research after confirming on its page', async () => {
    const f = deleteApi()
    function Page() {
      useQuery({ queryKey: ['research', 'a'], queryFn: () => fetch('/api/research/a').then((r) => r.json()) })
      return <p>research page</p>
    }
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/research/a']}>
          <Sidebar />
          <Routes>
            <Route path="/" element={<p>home</p>} />
            <Route path="/research/:id" element={<Page />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Nitrile gloves' }))
    const before = f.mock.calls.filter((c) => c[0] === '/api/research/a' && !c[1]?.method).length
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(await screen.findByText('home')).toBeInTheDocument()
    await waitFor(() => expect(deletes(f)).toHaveLength(1))
    expect(f.mock.calls.filter((c) => c[0] === '/api/research/a' && !c[1]?.method)).toHaveLength(before)
  })

  it('moves focus to Cancel when confirming and back to the trash button on cancel', async () => {
    deleteApi()
    renderWithClient('/')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Nitrile gloves' }))
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.getByRole('button', { name: 'Delete Nitrile gloves' })).toHaveFocus()
  })

  it('shows the 409 message inline', async () => {
    deleteApi(409)
    renderWithClient('/')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Nitrile gloves' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Cancel the research before deleting it.')
  })
})
