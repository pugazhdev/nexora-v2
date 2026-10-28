import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { RetailRow } from '@/api/types'
import { RetailCard } from './RetailCard'

const row = (retailer: string, unit: string, o: Partial<RetailRow> = {}): RetailRow => ({
  retailer,
  title: `${retailer} 2 ml syringe`,
  url: `https://${retailer.toLowerCase()}.example/p`,
  pack_size: 10,
  unit_price: unit,
  pack_price: String(Number(unit) * 10),
  price_quote: `₹${Number(unit) * 10}`,
  ...o,
})

describe('RetailCard', () => {
  it('lists rows lowest unit price first with product links', () => {
    const rows = [row('Netmeds', '14'), row('PharmEasy', '9.5'), row('Flipkart', '1.2', { pack_size: 1 })]
    render(<RetailCard retail={{ rows, notes: [], queries: [] }} running={false} />)
    expect(screen.getByRole('heading', { name: 'Retail price' })).toBeInTheDocument()
    const links = screen.getAllByRole('link')
    expect(links.map((a) => a.textContent)).toEqual([
      'Flipkart 2 ml syringe',
      'PharmEasy 2 ml syringe',
      'Netmeds 2 ml syringe',
    ])
    expect(links[0]).toHaveAttribute('href', 'https://flipkart.example/p')
    expect(links[0]).toHaveAttribute('target', '_blank')
    expect(links[0]).toHaveAttribute('rel', 'noopener noreferrer')
    const first = screen.getAllByRole('row')[1]!
    expect(within(first).getByText('Flipkart')).toBeInTheDocument()
    expect(within(first).getByText('₹1.20')).toBeInTheDocument()
    expect(within(first).getByText('Single unit')).toBeInTheDocument()
    expect(within(screen.getAllByRole('row')[2]!).getByText('Pack of 10')).toBeInTheDocument()
    expect(within(screen.getAllByRole('row')[2]!).getByText('₹95.00')).toBeInTheDocument()
    expect(screen.getByText('Retail prices for reference; they include retailer margin and GST.')).toBeInTheDocument()
  })

  it('shows at most five rows', () => {
    const rows = ['A', 'B', 'C', 'D', 'E', 'F'].map((r, i) => row(r, String(i + 1)))
    render(<RetailCard retail={{ rows, notes: [], queries: [] }} running={false} />)
    expect(screen.getAllByRole('link')).toHaveLength(5)
  })

  it('empty state when nothing was found or the run has no retail data', () => {
    const { rerender } = render(<RetailCard retail={{ rows: [], notes: ['Retail: x'], queries: [] }} running={false} />)
    expect(screen.getByText('No retail price found')).toBeInTheDocument()
    rerender(<RetailCard retail={null} running={false} />)
    expect(screen.getByText('No retail price found')).toBeInTheDocument()
  })

  it('running state while the item is still researching', () => {
    render(<RetailCard retail={null} running />)
    expect(screen.getByText('Finding retail prices...')).toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.queryByText('No retail price found')).toBeNull()
  })
})
