import { describe, expect, it } from 'vitest'
import cases from '../../../shared/calculator_cases.json'
import totalCases from '../../../shared/total_cases.json'
import type { Offer } from '@/api/types'
import { priceAt, purchaseRange, total } from './calculator'

type Case = (typeof cases)[number]

const toOffer = (o: Case['offers'][number]) => o as unknown as Offer

describe('purchaseRange shared cases', () => {
  it.each(cases.map((c) => [c.name, c] as const))('%s', (_n, c) => {
    const r = purchaseRange(c.offers.map(toOffer), c.quantity)
    const e = c.expected
    expect(r.lowestId).toBe(e.lowest_id)
    expect(r.lowestUnit).toBe(e.lowest_unit)
    expect(r.highestId).toBe(e.highest_id)
    expect(r.highestUnit).toBe(e.highest_unit)
    expect(r.fallbackAllMoq).toBe(e.fallback_all_moq)
    expect(r.unconfirmedOnly).toBe(e.unconfirmed_only)
  })
})

describe('total shared cases', () => {
  it.each(totalCases.map((c) => [`${c.unit}x${c.qty}`, c] as const))('%s', (_n, c) => {
    expect(total(Number(c.unit), c.qty, Number(c.gst_pct), Number(c.freight))).toBe(Number(c.expected))
  })
  it('matches the spec example', () => {
    expect(total(1.85, 50000, 5, 1500)).toBe(98625)
  })
})

describe('priceAt', () => {
  const tiers = [
    { min_qty: 50000, unit_price: '1.85' },
    { min_qty: 5000, unit_price: '2.10' },
  ]
  it('picks the highest tier not above qty regardless of order', () => {
    expect(priceAt(tiers, 49999)).toBe(2.1)
    expect(priceAt(tiers, 50000)).toBe(1.85)
  })
  it('returns null below the smallest tier', () => {
    expect(priceAt(tiers, 100)).toBeNull()
  })
})
