// Mirrors backend/app/research/tiers.py. Both run shared/calculator_cases.json and shared/total_cases.json.
import type { Offer, Tier } from '@/api/types'

export interface RangeResult {
  lowestId: string | null
  lowestUnit: string | null
  highestId: string | null
  highestUnit: string | null
  fallbackAllMoq: boolean
  unconfirmedOnly: boolean
}

export function priceAt(tiers: Tier[], qty: number): number | null {
  const hit = tiers.filter((t) => t.min_qty <= qty).sort((a, b) => a.min_qty - b.min_qty)
  const last = hit[hit.length - 1]
  return last ? Number(last.unit_price) : null
}

/** The offers the range is drawn from: in-range manufacturers, else in-range unconfirmed sellers. */
export function rangePool(offers: Offer[]): { pool: Offer[]; unconfirmedOnly: boolean } {
  const inRange = offers.filter((o) => o.in_range)
  const makers = inRange.filter((o) => o.classification === 'manufacturer')
  if (makers.length > 0) return { pool: makers, unconfirmedOnly: false }
  const pool = inRange.filter((o) => o.classification === 'unconfirmed')
  return { pool, unconfirmedOnly: pool.length > 0 }
}

// Unit prices stay strings; Number() is used only to compare them.
export function purchaseRange(offers: Offer[], qty: number): RangeResult {
  const { pool, unconfirmedOnly } = rangePool(offers)
  type P = { id: string; unit: string }
  let priced: P[] = []
  for (const o of pool) {
    if (o.moq !== null && o.moq > qty) continue
    const hit = o.tiers.filter((t) => t.min_qty <= qty).sort((a, b) => a.min_qty - b.min_qty)
    const last = hit[hit.length - 1]
    if (last) priced.push({ id: o.id, unit: last.unit_price })
  }
  const fallback = priced.length === 0 && pool.length > 0
  if (fallback) {
    priced = []
    for (const o of pool) {
      const first = [...o.tiers].sort((a, b) => a.min_qty - b.min_qty)[0]
      if (first) priced.push({ id: o.id, unit: first.unit_price })
    }
  }
  const [first, ...rest] = priced
  if (!first) {
    return {
      lowestId: null,
      lowestUnit: null,
      highestId: null,
      highestUnit: null,
      fallbackAllMoq: false,
      unconfirmedOnly,
    }
  }
  const byId = (a: P, b: P) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)
  let lo = first
  let hi = first
  for (const p of rest) {
    const [pu, lu, hu] = [Number(p.unit), Number(lo.unit), Number(hi.unit)]
    if (pu < lu || (pu === lu && byId(p, lo) < 0)) lo = p
    if (pu > hu || (pu === hu && byId(p, hi) < 0)) hi = p
  }
  return {
    lowestId: lo.id,
    lowestUnit: lo.unit,
    highestId: hi.id,
    highestUnit: hi.unit,
    fallbackAllMoq: fallback,
    unconfirmedOnly,
  }
}

const SCALE = 1_000_000n
const scaled = (n: number) => BigInt(Math.round(n * 1e6))

// Integer arithmetic (1e-6 resolution) so half-up rounding to whole rupees matches Python's Decimal.
export function total(unit: number, qty: number, gstPct: number, freight: number): number {
  const gross = scaled(unit) * BigInt(qty) * (100n * SCALE + scaled(gstPct)) // scale 1e12 * 100
  const denom = 100n * SCALE * SCALE
  const num = gross + scaled(freight) * 100n * SCALE
  const sign = num < 0n ? -1n : 1n
  const abs = num * sign
  return Number(sign * ((abs * 2n + denom) / (denom * 2n)))
}
