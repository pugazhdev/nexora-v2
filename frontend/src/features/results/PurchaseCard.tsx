import { useState } from 'react'
import type { ItemResult, Offer } from '@/api/types'
import { Glass } from '@/components/ui/Glass'
import { Tag } from '@/components/ui/Tag'
import { purchaseRange, rangePool, total } from '@/lib/calculator'
import { formatInr, parseIndianNumber } from '@/lib/format'
import { ROUGH_NOTE } from './CostCard'
import { ManufacturerList } from './ManufacturerList'
import { where } from './offerText'

const num = (s: string) => (s.trim() === '' ? 0 : parseIndianNumber(s))

function End({ label, o, unit, cls }: { label: string; o: Offer; unit: string; cls: string }) {
  return (
    <a className={`end ${cls}`} href={o.url} target="_blank" rel="noopener noreferrer">
      <span className="lab">{label}</span>
      <span className="amt">
        {formatInr(Number(unit))}
        <small> / unit</small>
      </span>
      <span className="who">{o.manufacturer} ↗</span>
      <span className="where">
        {[where(o), o.moq ? `Min ${o.moq.toLocaleString('en-IN')}` : ''].filter(Boolean).join(' · ')}
      </span>
    </a>
  )
}

export function PurchaseCard({
  result,
  units: initialUnits,
  starred = [],
}: {
  result: ItemResult
  units: number
  starred?: string[]
}) {
  const [u, setU] = useState(initialUnits > 0 ? initialUnits.toLocaleString('en-IN') : '')
  const [g, setG] = useState(result.gst?.rate_pct ?? '')
  const [f, setF] = useState('0')
  const offers = result.offers.filter((o) => o.classification !== 'excluded')
  const parsed = parseIndianNumber(u)
  const units = parsed !== null && Number.isInteger(parsed) && parsed > 0 ? parsed : null
  const gst = num(g)
  const freight = num(f)
  const qty = units ?? (initialUnits > 0 ? initialUnits : 1)
  const range = purchaseRange(offers, qty)
  const byId = (id: string | null) => offers.find((o) => o.id === id)
  const lo = byId(range.lowestId)
  const hi = byId(range.highestId)
  const sum = (unit: string | null) =>
    unit !== null && units !== null && gst !== null && freight !== null
      ? formatInr(total(Number(unit), units, gst, freight), 0)
      : '-'
  const notes = result.notes.filter((n) => n !== ROUGH_NOTE)
  const n = rangePool(offers).pool.length // G4: only the offers the range is drawn from
  const list = (
    <ManufacturerList offers={offers} qty={qty} units={units} gst={gst} freight={freight} starred={starred} />
  )

  return (
    <Glass className="rc">
      <div className="rc-head">
        <h2>Factory purchase price</h2>
        {lo && <span className="muted">{n === 1 ? '1 manufacturer' : `${n} manufacturers`}</span>}
      </div>
      {!lo ? (
        <>
          <p className="muted">{offers.length > 0 ? 'No comparable price found' : 'No manufacturer found'}</p>
          {offers.length > 0 && list}
          {result.queries.length > 0 && (
            <details className="all">
              <summary>Searches used</summary>
              {result.queries.map((q) => (
                <div key={q} className="muted small">
                  {q}
                </div>
              ))}
            </details>
          )}
        </>
      ) : (
        <>
          {range.unconfirmedOnly && <Tag tone="warn">Unconfirmed sellers only</Tag>}
          {range.fallbackAllMoq && <div className="muted small">All manufacturers need a larger order</div>}
          <div className={lo.id === hi?.id ? 'range one' : 'range'}>
            <End label="Lowest" o={lo} unit={range.lowestUnit!} cls="lo" />
            {hi && hi.id !== lo.id && <End label="Highest" o={hi} unit={range.highestUnit!} cls="hi" />}
          </div>
          <div className="calc2">
            <label>
              Units
              <input
                value={u}
                onChange={(e) => setU(e.target.value)}
                inputMode="numeric"
                aria-invalid={units === null}
              />
            </label>
            <label>
              GST %
              <input value={g} onChange={(e) => setG(e.target.value)} inputMode="decimal" aria-invalid={gst === null} />
            </label>
            <label>
              Freight ₹
              <input
                value={f}
                onChange={(e) => setF(e.target.value)}
                inputMode="decimal"
                aria-invalid={freight === null}
              />
            </label>
          </div>
          <div className="tot">
            <span>Total at lowest</span>
            <b>{sum(range.lowestUnit)}</b>
          </div>
          {hi && hi.id !== lo.id && (
            <div className="tot">
              <span>Total at highest</span>
              <b>{sum(range.highestUnit)}</b>
            </div>
          )}
          {list}
        </>
      )}
      {notes.length > 0 && (
        <details className="all">
          <summary>Notes</summary>
          {notes.map((t) => (
            <div key={t} className="muted small">
              {t}
            </div>
          ))}
        </details>
      )}
    </Glass>
  )
}
