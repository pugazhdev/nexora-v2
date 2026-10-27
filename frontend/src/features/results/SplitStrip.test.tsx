import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ItemRun } from '@/api/types'
import { item } from '../research/fixtures'
import { offer, result } from './fixtures'
import { SplitStrip } from './SplitStrip'

const parts = [
  { name: 'Barrel', typical_material: 'PP', count_per_unit: 1 },
  { name: 'Needle', typical_material: 'SS', count_per_unit: 2 },
]
const mk = (o: Partial<ItemRun> = {}) =>
  ({
    id: 'r',
    item_id: 'i1',
    status: 'done',
    result: result(),
    split_status: null,
    split: null,
    split_error: null,
    ...o,
  }) as ItemRun
const show = (run: ItemRun, splittable = true, p = parts) =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <SplitStrip item={item({ splittable, parts: p })} run={run} researchId="r1" />
    </QueryClientProvider>,
  )
afterEach(() => vi.unstubAllGlobals())

describe('SplitStrip', () => {
  it('hidden when not splittable or no parts', () => {
    const a = show(mk(), false)
    expect(a.container).toBeEmptyDOMElement()
    const b = show(mk(), true, [])
    expect(b.container).toBeEmptyDOMElement()
  })
  it('chips with counts and the action', async () => {
    const f = vi.fn(async () => new Response('{"status":"running"}'))
    vi.stubGlobal('fetch', f)
    show(mk())
    expect(screen.getByText('Barrel')).toBeInTheDocument()
    expect(screen.getByText('Needle x 2')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Split and research' }))
    expect(f).toHaveBeenCalledWith('/api/items/i1/split', expect.objectContaining({ method: 'POST' }))
  })
  it('running state', () => {
    show(mk({ split_status: 'running' }))
    expect(screen.getByText('Researching parts...')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Researching parts/ })).toBeDisabled()
  })
  it('done shows table and parts total', () => {
    const split = {
      parts: [
        {
          part: 'Barrel',
          count_per_unit: 1,
          offer: offer('a', { manufacturer: 'Polymould', tiers: [{ min_qty: 1, unit_price: '0.31' }] }),
          notes: [],
        },
        {
          part: 'Needle',
          count_per_unit: 2,
          offer: offer('b', { manufacturer: 'Cannula', tiers: [{ min_qty: 1, unit_price: '0.52' }] }),
          notes: [],
        },
      ],
      parts_total: '1.35',
      finished_lowest: '1.85',
      complete: true,
    }
    show(mk({ split_status: 'done', split }))
    expect(screen.getByRole('link', { name: /Polymould/ })).toBeInTheDocument()
    expect(
      screen.getByText('Parts total ₹1.35 vs ₹1.85 lowest finished, before your assembly cost'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Research again' })).toBeInTheDocument()
  })
  it('incomplete', () => {
    const split = {
      parts: [{ part: 'Barrel', count_per_unit: 1, offer: null, notes: [] }],
      parts_total: null,
      finished_lowest: '1.85',
      complete: false,
    }
    show(mk({ split_status: 'done', split }))
    expect(screen.getByText('No manufacturer found')).toBeInTheDocument()
    expect(screen.getByText('Total incomplete')).toBeInTheDocument()
  })
  it('failed split with an empty split object does not crash', () => {
    show(mk({ split_status: 'failed', split_error: 'Boom', split: {} as never }))
    expect(screen.getByRole('alert')).toHaveTextContent('Boom')
    expect(screen.getByRole('button', { name: 'Split and research' })).toBeInTheDocument()
  })
  it('part unit matches the backend branch: moq above the part quantity uses the first tier', () => {
    const o = offer('a', {
      manufacturer: 'Polymould',
      moq: 100000,
      tiers: [
        { min_qty: 100000, unit_price: '0.40' },
        { min_qty: 200000, unit_price: '0.30' },
      ],
    })
    const split = {
      parts: [{ part: 'Needle', count_per_unit: 2, offer: o, notes: [] }],
      parts_total: '0.80',
      finished_lowest: '1.85',
      complete: true,
    }
    show(mk({ split_status: 'done', split }))
    expect(screen.getByText('₹0.40')).toBeInTheDocument()
    expect(screen.getByText('Needle x 2', { selector: 'td' })).toBeInTheDocument()
  })
  it('tags a part maker Unconfirmed unless it is a manufacturer (I4)', () => {
    const split = {
      parts: [
        { part: 'Barrel', count_per_unit: 1, offer: offer('a', { manufacturer: 'Polymould' }), notes: [] },
        {
          part: 'Needle',
          count_per_unit: 1,
          offer: offer('b', { manufacturer: 'Cannula', classification: 'unconfirmed' }),
          notes: [],
        },
      ],
      parts_total: '4.00',
      finished_lowest: null,
      complete: true,
    }
    show(mk({ split_status: 'done', split }))
    expect(screen.getAllByText('Unconfirmed')).toHaveLength(1)
    expect(screen.getByText('Unconfirmed').closest('td')).toHaveTextContent('Cannula')
  })
  it('failed shows the error inline', () => {
    show(mk({ split_status: 'failed', split_error: 'Boom' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Boom')
  })
})
