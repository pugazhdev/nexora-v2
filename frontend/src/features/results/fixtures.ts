import type { CostEstimate, ItemResult, Offer } from '@/api/types'

export const offer = (id: string, o: Partial<Offer> = {}): Offer => ({
  id,
  manufacturer: `Maker ${id}`,
  city: 'Ahmedabad',
  state: null,
  platform: 'IndiaMART',
  url: `https://example.com/${id}`,
  classification: 'manufacturer',
  tiers: [{ min_qty: 1, unit_price: '2.00' }],
  moq: null,
  in_range: true,
  flags: [],
  extra_links: [],
  price_quote: '',
  spec_match: 'match',
  observed_at: null,
  gst_rate_pct: null,
  ...o,
})

export const cost = (o: Partial<CostEstimate> = {}): CostEstimate => ({
  per_unit: '1.42',
  low: '1.20',
  high: '1.70',
  confidence: 'medium',
  lines: [
    { label: 'PP resin', amount: '0.34', basis: '3.1 g', source_ids: [1], estimated: false, quote: 'PP at 110 per kg' },
    { label: 'Packing', amount: '0.17', basis: '', source_ids: [], estimated: true, quote: null },
  ],
  sources: [{ id: 1, url: 'https://plastemart.com/pp', title: 'PP price' }],
  ...o,
})

export const result = (o: Partial<ItemResult> = {}): ItemResult => ({
  spec_title: 'Syringe',
  quantity: 50000,
  cost: cost(),
  offers: [],
  gst: null,
  notes: [],
  queries: ['syringe manufacturer'],
  ...o,
})
