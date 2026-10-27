import type { CostEstimate } from '@/api/types'
import { Glass } from '@/components/ui/Glass'
import { Tag } from '@/components/ui/Tag'
import { formatInr } from '@/lib/format'

export const ROUGH_NOTE = 'Estimated making cost is above the lowest market price; treat it as rough.'
const CONF = { high: 'High', medium: 'Medium', low: 'Low' }
const TONE = { high: 'ok', medium: 'warn', low: 'bad' } as const
const inr = (v: string) => formatInr(Number(v))

export function CostCard({ cost, notes }: { cost: CostEstimate | null; notes: string[] }) {
  return (
    <Glass className="rc">
      <div className="rc-head">
        <h2>Manufacturing cost</h2>
        {cost && <Tag tone={TONE[cost.confidence]}>{CONF[cost.confidence]} confidence</Tag>}
      </div>
      {!cost ? (
        <p className="muted">Cost estimate unavailable</p>
      ) : (
        <>
          <div className="big">
            {inr(cost.per_unit)}
            <small> / unit</small>
          </div>
          <div className="muted">
            Likely between {inr(cost.low)} and {inr(cost.high)}
          </div>
          {notes.includes(ROUGH_NOTE) && <div className="muted small">{ROUGH_NOTE}</div>}
          <div className="rows">
            {cost.lines.map((l, n) => (
              <div key={n}>
                <div className="li">
                  <span>
                    {l.label}
                    {l.source_ids.map((id) => {
                      const s = cost.sources.find((x) => x.id === id)
                      return (
                        <sup key={id}>
                          {s ? (
                            <a href={s.url} target="_blank" rel="noopener noreferrer">
                              {id}
                            </a>
                          ) : (
                            id
                          )}
                        </sup>
                      )
                    })}
                    {l.estimated && <Tag className="est">estimate, no source</Tag>}
                  </span>
                  <b>{inr(l.amount)}</b>
                </div>
                {l.quote && <div className="muted small quote">{l.quote}</div>}
              </div>
            ))}
          </div>
          {cost.sources.length > 0 && (
            <div className="sources">
              {cost.sources.map((s) => (
                <div key={s.id} className="src">
                  {s.id}{' '}
                  <a href={s.url} target="_blank" rel="noopener noreferrer">
                    {s.title}
                  </a>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Glass>
  )
}
