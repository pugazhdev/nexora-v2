import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Star } from 'lucide-react'
import { useState } from 'react'
import { api } from '@/api/client'
import type { Manufacturer, Offer } from '@/api/types'
import { Tag } from '@/components/ui/Tag'
import { formatInr } from '@/lib/format'
import { total } from '@/lib/calculator'
import { normName, unitAt, where } from './offerText'

const FLAG_TEXT: Record<string, string> = {
  price_on_request: 'Price on request',
  spec_unstated: 'Spec not confirmed',
  spec_partly_confirmed: 'Spec partly confirmed',
  older_listing: 'Older listing',
  unusually_low: 'Unusually low',
  unusually_high: 'Unusually high',
  outlier: 'Unusually high',
  incl_gst_rate_unknown: 'Incl. GST rate not stated',
  basis_unclear: 'Price basis unclear',
  ambiguous_variants: 'Several variants',
  conflicting_seller_type: 'Seller type unclear',
}

/** Star by manufacturer name: Offer carries no manufacturer id, so look it up first. */
function StarButton({ name, seeded }: { name: string; seeded: boolean }) {
  const qc = useQueryClient()
  const [override, setOverride] = useState<boolean | null>(null)
  const starred = override ?? seeded
  const toggle = useMutation({
    mutationFn: async () => {
      const rows = await api.get<Manufacturer[]>(`/manufacturers?q=${encodeURIComponent(name)}`)
      const m = rows.find((r) => normName(r.name) === normName(name))
      if (!m) throw new Error('Manufacturer not saved yet, cannot star')
      await api.patch<Manufacturer>(`/manufacturers/${m.id}`, { starred: !starred })
    },
    onSuccess: () => {
      setOverride(!starred)
      return qc.invalidateQueries({ queryKey: ['manufacturers'] })
    },
  })
  return (
    <>
      <button
        type="button"
        className={`star${starred ? ' on' : ''}`}
        aria-label={`${starred ? 'Unstar' : 'Star'} ${name}`}
        aria-pressed={starred}
        disabled={toggle.isPending}
        onClick={() => toggle.mutate()}
      >
        <Star size={14} fill={starred ? 'currentColor' : 'none'} />
      </button>
      {toggle.error && (
        <span className="field-error small star-err" role="alert">
          {toggle.error.message}
        </span>
      )}
    </>
  )
}

/** units/gst/freight are null when the user's input is invalid: totals then show a dash. */
export function ManufacturerList({
  offers,
  qty,
  units,
  gst,
  starred,
  freight,
}: {
  offers: Offer[]
  qty: number
  units: number | null
  gst: number | null
  freight: number | null
  starred: string[]
}) {
  const rows = offers
    .map((o) => {
      const unit = unitAt(o, qty)
      const below = o.moq !== null && o.moq > qty
      const sum =
        units !== null && gst !== null && freight !== null && Number.isFinite(unit)
          ? total(unit, units, gst, freight)
          : null
      return { o, unit, below, sum }
    })
    .sort(
      (a, b) =>
        Number(a.below) - Number(b.below) ||
        (Number.isFinite(a.unit) ? a.unit : 1e18) - (Number.isFinite(b.unit) ? b.unit : 1e18),
    )
  return (
    <details className="all">
      <summary>All manufacturers</summary>
      <div data-testid="all-manufacturers">
        {rows.map(({ o, unit, below, sum }) => (
          <div key={o.id} className={`mrow${below ? ' below' : ''}`}>
            <div>
              <a href={o.url} target="_blank" rel="noopener noreferrer">
                {o.manufacturer}
              </a>{' '}
              {o.classification === 'manufacturer' ? (
                <Tag tone="ok">Manufacturer</Tag>
              ) : (
                <Tag tone="warn">Unconfirmed</Tag>
              )}
              {below && <Tag tone="bad">Min {o.moq!.toLocaleString('en-IN')}</Tag>}
              {[...new Set(o.flags.map((f) => FLAG_TEXT[f]).filter(Boolean))].map((t) => (
                <Tag key={t}>{t}</Tag>
              ))}
              <div className="muted small">{where(o)}</div>
            </div>
            <div className="r">
              <b>{Number.isFinite(unit) ? formatInr(unit) : '-'}</b>
              {sum === null ? '-' : formatInr(sum, 0)}
            </div>
            <StarButton name={o.manufacturer} seeded={starred.includes(normName(o.manufacturer))} />
          </div>
        ))}
      </div>
    </details>
  )
}
