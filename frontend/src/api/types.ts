// Mirrors backend JSON. Money/Decimal fields are strings; datetimes are UTC ISO strings ending in Z.

export type Money = string
export type Iso = string

export interface ApiErrorBody {
  error: { code: string; message: string; details: unknown }
}

export interface Option {
  value: string
  label: string
}

export interface Question {
  key: string
  label: string
  help: string | null
  kind: 'single' | 'multi' | 'number' | 'text' | 'boolean'
  options: Option[]
  unit: string | null
  min: number | null
  max: number | null
  default: string | number | boolean | string[] | null
  required: boolean
  price_relevant: boolean
}

export interface KnownAttribute {
  key: string
  label: string
  value: string
  evidence: 'visible on pack' | 'stated in text' | 'inferred'
}

export interface Part {
  name: string
  typical_material: string
  count_per_unit: number
}

export interface Tier {
  min_qty: number
  unit_price: Money
}

export interface Offer {
  id: string
  manufacturer: string
  city: string | null
  state: string | null
  platform: string
  url: string
  classification: 'manufacturer' | 'unconfirmed' | 'excluded'
  tiers: Tier[]
  moq: number | null
  in_range: boolean
  flags: string[]
  extra_links: string[]
  price_quote: string
  spec_match: 'match' | 'mismatch' | 'unstated' | 'ambiguous'
  observed_at: string | null // YYYY-MM-DD
  gst_rate_pct: Money | null
}

export interface CostLine {
  label: string
  amount: Money
  basis: string
  source_ids: number[]
  estimated: boolean
  quote: string | null
}

export interface Source {
  id: number
  url: string
  title: string
}

export interface CostEstimate {
  per_unit: Money
  low: Money
  high: Money
  confidence: 'high' | 'medium' | 'low'
  lines: CostLine[]
  sources: Source[]
}

export interface GstPrefill {
  rate_pct: Money
  source_url: string
}

export interface ItemResult {
  spec_title: string
  quantity: number
  cost: CostEstimate | null
  offers: Offer[]
  gst: GstPrefill | null
  notes: string[]
  queries: string[]
}

export interface PartResult {
  part: string
  count_per_unit: number
  offer: Offer | null
  notes: string[]
}

export interface SplitResult {
  parts: PartResult[]
  parts_total: Money | null
  finished_lowest: Money | null
  complete: boolean
}

/** item_run.retail: retail prices for reference, kept apart from ItemResult. */
export interface RetailRow {
  retailer: string
  title: string
  url: string
  pack_size: number
  unit_price: Money
  pack_price: Money
  price_quote: string
}

export interface RetailResult {
  rows: RetailRow[]
  notes: string[]
  queries: string[]
}

export type RunStatus = 'queued' | 'researching' | 'done' | 'failed' | 'cancelled' | 'interrupted'

/** The latest_run row on an item (item_run table). */
export interface ItemRun {
  id: string
  item_id: string
  answers: Record<string, unknown>
  spec: Record<string, unknown>
  status: RunStatus
  result: ItemResult | null
  error: string | null
  split_status: 'running' | 'done' | 'failed' | 'interrupted' | null
  split: SplitResult | null
  split_error: string | null
  /** null while the lookup runs, and for runs made before retail prices existed */
  retail?: RetailResult | null
  created_at: Iso
  started_at: Iso | null
  finished_at: Iso | null
}

export type ItemCategory = 'consumable' | 'medicine' | 'equipment' | 'not_medical' | 'unclear'

export interface ResearchItem {
  id: string
  position: number
  name: string
  category: ItemCategory | null
  in_scope: boolean
  scope_reason: string | null
  selected: boolean
  known_attributes: KnownAttribute[]
  questions: Question[]
  answers: Record<string, string | number | boolean | string[]>
  answer_errors: Record<string, string>
  splittable: boolean
  parts: Part[]
  image_region_hint: string
  latest_run: ItemRun | null
}

export type ResearchStatus = 'draft' | 'researching' | 'done'

export interface Research {
  id: string
  title: string
  created_at: Iso
  image_path: string | null
  status: ResearchStatus
  message: string | null
  items: ResearchItem[]
}

/** GET /api/research rows. */
export interface ResearchSummary {
  item_count: number
  id: string
  title: string
  created_at: Iso
  status: ResearchStatus
}

/** SSE "step" event (run_event row plus item_id). */
export interface RunEvent {
  id: number
  run_id: string
  item_id: string
  at: Iso
  phase: string
  level: 'info' | 'warn' | 'error' | string
  message: string
}

/** SSE "status" event. */
export interface RunSnapshot {
  status: ResearchStatus
  items: { item_id: string; run_id: string; status: RunStatus; error: string | null }[]
}

export interface Manufacturer {
  id: string
  name: string
  city: string | null
  state: string | null
  website: string | null
  platforms: string[]
  listing_count: number
  last_seen: Iso | null
  starred: boolean
  /** true when any listing of this maker was classified manufacturer */
  confirmed: boolean
}

export interface AppSettings {
  openai_configured: boolean
  tavily_configured: boolean
  model: string
  vision_model: string
  budgets: Record<string, number>
  research_concurrency: number
  denylist: string[]
}
