import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { offer, result } from './fixtures'
import { PurchaseCard } from './PurchaseCard'

const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 })
const show = (r = result(), units = 1000, starred: string[] = []) =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <PurchaseCard result={r} units={units} starred={starred} />
    </QueryClientProvider>,
  )
afterEach(() => vi.unstubAllGlobals())
const tot = (label: string) => screen.getByText(label).nextSibling

const two = result({
  offers: [
    offer('a', {
      manufacturer: 'Alpha',
      tiers: [
        { min_qty: 1, unit_price: '2.10' },
        { min_qty: 5000, unit_price: '1.50' },
      ],
    }),
    offer('b', { manufacturer: 'Beta', tiers: [{ min_qty: 1, unit_price: '1.80' }] }),
  ],
})

describe('PurchaseCard', () => {
  it('recomputes totals and switches the lowest offer at a tier threshold', async () => {
    show(two, 1000)
    expect(screen.getByRole('link', { name: /Lowest/ })).toHaveTextContent('Beta')
    expect(tot('Total at lowest')).toHaveTextContent('₹1,800')
    const u = screen.getByLabelText('Units')
    await userEvent.clear(u)
    await userEvent.type(u, '5,000')
    expect(screen.getByRole('link', { name: /Lowest/ })).toHaveTextContent('Alpha')
    expect(tot('Total at lowest')).toHaveTextContent('₹7,500')
  })
  it('GST is prefilled, editable and applied; empty means 0', async () => {
    show(result({ ...two, gst: { rate_pct: '5', source_url: 'x' } }), 1000)
    const g = screen.getByLabelText('GST %')
    expect(g).toHaveValue('5')
    expect(tot('Total at lowest')).toHaveTextContent('₹1,890')
    await userEvent.clear(g)
    expect(tot('Total at lowest')).toHaveTextContent('₹1,800')
    await userEvent.type(g, '12')
    expect(tot('Total at lowest')).toHaveTextContent('₹2,016')
  })
  it('GST empty when the result has none', () => {
    show(two)
    expect(screen.getByLabelText('GST %')).toHaveValue('')
  })
  it('blank totals for a non-integer Units', async () => {
    show(two)
    const u = screen.getByLabelText('Units')
    await userEvent.clear(u)
    await userEvent.type(u, '10.5')
    expect(tot('Total at lowest')).toHaveTextContent('-')
  })
  it('unconfirmed label', () => {
    show(result({ offers: [offer('a', { classification: 'unconfirmed' })] }))
    expect(screen.getByText('Unconfirmed sellers only')).toBeInTheDocument()
  })
  it('fallback note when every maker needs a larger order', () => {
    show(result({ offers: [offer('a', { moq: 5000 })] }), 100)
    expect(screen.getByText('All manufacturers need a larger order')).toBeInTheDocument()
  })
  it('single offer', () => {
    show(result({ offers: [offer('a')] }))
    expect(screen.getByText('1 manufacturer')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Highest/ })).toBeNull()
  })
  it('empty state with queries', () => {
    show(result({ offers: [] }))
    expect(screen.getByText('No manufacturer found')).toBeInTheDocument()
    expect(screen.getByText('syringe manufacturer')).toBeInTheDocument()
  })
  it('all manufacturers list: tags, min N, hides excluded', () => {
    show(
      result({
        offers: [
          offer('a', { manufacturer: 'Alpha', flags: ['older_listing'] }),
          offer('b', { manufacturer: 'Beta', classification: 'unconfirmed', moq: 5000 }),
          offer('x', { manufacturer: 'Gone', classification: 'excluded' }),
        ],
      }),
    )
    const list = screen.getByTestId('all-manufacturers')
    expect(within(list).getByText('Older listing')).toBeInTheDocument()
    expect(within(list).getByText('Min 5,000')).toBeInTheDocument()
    expect(within(list).getByText('Unconfirmed')).toBeInTheDocument()
    expect(screen.queryByText('Gone')).toBeNull()
  })
  it('star looks the manufacturer up by name then patches', async () => {
    const f = vi.fn(async (u: string, _init?: RequestInit) =>
      json(u.includes('?q=') ? [{ id: 'm1', name: 'Alpha', starred: false }] : { id: 'm1', starred: true }),
    )
    vi.stubGlobal('fetch', f)
    show(result({ offers: [offer('a', { manufacturer: 'Alpha' })] }))
    await userEvent.click(screen.getByRole('button', { name: 'Star Alpha' }))
    expect(await screen.findByRole('button', { name: 'Unstar Alpha' })).toBeInTheDocument()
    expect(f.mock.calls.map((c) => [c[0], (c as unknown[])[1] && ((c as unknown[])[1] as RequestInit).method])).toEqual(
      [
        ['/api/manufacturers?q=Alpha', 'GET'],
        ['/api/manufacturers/m1', 'PATCH'],
      ],
    )
  })
  it('starring invalidates every manufacturers query', async () => {
    vi.stubGlobal('fetch', vi.fn(async (u: string) => json(u.includes('?q=') ? [{ id: 'm1', name: 'Alpha' }] : {})))
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    render(
      <QueryClientProvider client={qc}>
        <PurchaseCard result={result({ offers: [offer('a', { manufacturer: 'Alpha' })] })} units={1000} starred={[]} />
      </QueryClientProvider>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Star Alpha' }))
    await screen.findByRole('button', { name: 'Unstar Alpha' })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['manufacturers'] })
  })
  it('pre-starred maker renders starred; click unstars with an explicit target', async () => {
    const f = vi.fn(async (u: string) =>
      json(u.includes('?q=') ? [{ id: 'm1', name: 'Alpha Pvt. Ltd.', starred: true }] : { id: 'm1', starred: false }),
    )
    vi.stubGlobal('fetch', f)
    show(result({ offers: [offer('a', { manufacturer: 'Alpha Private Limited' })] }), 1000, ['alpha'])
    await userEvent.click(screen.getByRole('button', { name: 'Unstar Alpha Private Limited' }))
    expect(await screen.findByRole('button', { name: 'Star Alpha Private Limited' })).toBeInTheDocument()
    const patch = f.mock.calls.find(
      (c) => (c as unknown[])[1] && ((c as unknown[])[1] as RequestInit).method === 'PATCH',
    )!
    expect(JSON.parse(((patch as unknown[])[1] as RequestInit).body as string)).toEqual({ starred: false })
  })
  it('star errors show inline', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json([])),
    )
    show(result({ offers: [offer('a', { manufacturer: 'Alpha' })] }))
    await userEvent.click(screen.getByRole('button', { name: 'Star Alpha' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('cannot star')
  })
  it('list prices follow the same quantity as the cards while Units is invalid', async () => {
    show(two, 5000)
    const u = screen.getByLabelText('Units')
    await userEvent.clear(u)
    await userEvent.type(u, '10.5')
    expect(screen.getByRole('link', { name: /Lowest/ })).toHaveTextContent('₹1.50')
    expect(within(screen.getByTestId('all-manufacturers')).getByText('₹1.50')).toBeInTheDocument()
  })
  it('lists price-on-request makers with links when no offer is priced (I3)', () => {
    show(
      result({
        offers: [
          offer('a', { manufacturer: 'Alpha', tiers: [], in_range: false, flags: ['price_on_request'] }),
          offer('b', { manufacturer: 'Beta', in_range: false, flags: ['ambiguous_variants'] }),
        ],
      }),
    )
    expect(screen.queryByText('No manufacturer found')).toBeNull()
    const list = screen.getByTestId('all-manufacturers')
    expect(within(list).getByRole('link', { name: 'Alpha' })).toHaveAttribute('href', 'https://example.com/a')
    expect(within(list).getByText('Price on request')).toBeInTheDocument()
    expect(within(list).getByText('Several variants')).toBeInTheDocument()
  })
  it('manufacturer count is the range pool only (G4)', () => {
    show(
      result({
        offers: [
          offer('a'),
          offer('b'),
          offer('c', { in_range: false }),
          offer('d', { classification: 'unconfirmed' }),
        ],
      }),
    )
    expect(screen.getByText('2 manufacturers')).toBeInTheDocument()
  })
  it('notes collapsed at the bottom', () => {
    show(result({ offers: [offer('a')], notes: ['Stopped early'] }))
    expect(screen.getByText('Notes')).toBeInTheDocument()
  })
})
