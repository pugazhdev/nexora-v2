import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { api } from '@/api/client'
import type { ItemRun, Offer, ResearchItem } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { Glass } from '@/components/ui/Glass'
import { Spinner } from '@/components/ui/Spinner'
import { Tag } from '@/components/ui/Tag'
import { formatInr } from '@/lib/format'
import { researchKey } from '../research/useResearch'
import { purchaseRange } from '@/lib/calculator'
import { where } from './offerText'

// Same branch as the backend: purchase range over this one offer at the part quantity.
const unitCell = (o: Offer, qty: number) => {
  const u = purchaseRange([o], qty).lowestUnit
  return u === null ? '-' : formatInr(Number(u))
}

export function SplitStrip({ item, run, researchId }: { item: ResearchItem; run: ItemRun; researchId: string }) {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: researchKey(researchId) })
  const start = useMutation({ mutationFn: () => api.post(`/items/${item.id}/split`), onSettled: refresh })
  const running = run.split_status === 'running'
  // ponytail: polls the research query every 3 s while running; the SSE hook is not worth reusing here.
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => qc.invalidateQueries({ queryKey: researchKey(researchId) }), 3000)
    return () => clearInterval(t)
  }, [running, qc, researchId])
  if (!item.splittable || item.parts.length === 0) return null
  const split = run.split_status === 'done' ? run.split : null
  const qty = run.result?.quantity ?? 1
  const busy = running || start.isPending
  const err =
    start.error?.message ??
    (run.split_status === 'failed'
      ? (run.split_error ?? 'Splitting failed')
      : run.split_status === 'interrupted'
        ? 'Interrupted by a server restart'
        : null)
  return (
    <Glass className="split">
      <div className="split-top">
        <div>
          <h2>Can be bought as parts</h2>
          <div className="parts">
            {item.parts.map((p) => (
              <span key={p.name}>{p.count_per_unit > 1 ? `${p.name} x ${p.count_per_unit}` : p.name}</span>
            ))}
          </div>
        </div>
        <Button disabled={busy} onClick={() => start.mutate()}>
          {busy ? (
            <>
              <Spinner label="Running" /> Researching parts...
            </>
          ) : split ? (
            'Research again'
          ) : (
            'Split and research'
          )}
        </Button>
      </div>
      {err && (
        <p className="field-error" role="alert">
          {err}
        </p>
      )}
      {split && !running && (
        <>
          <table className="split-table">
            <thead>
              <tr>
                <th>Part</th>
                <th>Cheapest maker</th>
                <th className="r">Unit price</th>
              </tr>
            </thead>
            <tbody>
              {split.parts.map((p) => (
                <tr key={p.part}>
                  <td>{p.count_per_unit > 1 ? `${p.part} x ${p.count_per_unit}` : p.part}</td>
                  {p.offer ? (
                    <>
                      <td>
                        <a href={p.offer.url} target="_blank" rel="noopener noreferrer">
                          {p.offer.manufacturer} ↗
                        </a>
                        {p.offer.classification !== 'manufacturer' && <Tag tone="warn">Unconfirmed</Tag>}
                        <div className="sub muted small">{where(p.offer)}</div>
                      </td>
                      <td className="r">{unitCell(p.offer, qty * p.count_per_unit)}</td>
                    </>
                  ) : (
                    <td colSpan={2} className="muted">
                      No manufacturer found
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="split-total">
            {split.complete && split.parts_total !== null ? (
              <>
                Parts total {formatInr(Number(split.parts_total))}
                {split.finished_lowest !== null && ` vs ${formatInr(Number(split.finished_lowest))} lowest finished`},
                before your assembly cost
              </>
            ) : (
              'Total incomplete'
            )}
          </p>
        </>
      )}
    </Glass>
  )
}
