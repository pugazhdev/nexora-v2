import type { Offer } from '@/api/types'
import { priceAt } from '@/lib/calculator'

export const where = (o: Offer) => [o.city, o.platform].filter(Boolean).join(' · ')
export const unitAt = (o: Offer, qty: number) =>
  priceAt(o.tiers, qty) ?? Number([...o.tiers].sort((a, b) => a.min_qty - b.min_qty)[0]?.unit_price)

export const normName = (s: string) =>
  s
    .toLowerCase()
    .replace(/[.,]/g, ' ')
    .replace(/\b(pvt|ltd|private|limited)\b/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
