import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { CostCard } from './CostCard'
import { cost } from './fixtures'

describe('CostCard', () => {
  it('shows per unit, range, confidence, lines, sources', () => {
    render(<CostCard cost={cost()} notes={[]} />)
    expect(screen.getByText('₹1.42')).toBeInTheDocument()
    expect(screen.getByText('Likely between ₹1.20 and ₹1.70')).toBeInTheDocument()
    expect(screen.getByText('Medium confidence')).toBeInTheDocument()
    expect(screen.getByText('estimate, no source')).toBeInTheDocument()
    expect(screen.getByText('PP at 110 per kg')).toBeInTheDocument()
    const src = screen.getByRole('link', { name: 'PP price' })
    expect(src).toHaveAttribute('href', 'https://plastemart.com/pp')
    expect(src).toHaveAttribute('target', '_blank')
    expect(src).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })
  it('empty state', () => {
    render(<CostCard cost={null} notes={[]} />)
    expect(screen.getByText('Cost estimate unavailable')).toBeInTheDocument()
  })
  it('shows the rough-estimate note only when present', () => {
    const n = 'Estimated making cost is above the lowest market price; treat it as rough.'
    const { rerender } = render(<CostCard cost={cost()} notes={[n]} />)
    expect(screen.getByText(n)).toBeInTheDocument()
    rerender(<CostCard cost={cost()} notes={[]} />)
    expect(screen.queryByText(n)).toBeNull()
  })
})
