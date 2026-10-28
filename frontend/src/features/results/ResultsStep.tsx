import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '@/api/client'
import type { ItemRun, Manufacturer, Research } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { researchKey } from '../research/useResearch'
import { normName } from './offerText'
import { CostCard } from './CostCard'
import { PurchaseCard } from './PurchaseCard'
import { RetailCard } from './RetailCard'
import { SplitStrip } from './SplitStrip'

const STATUS = { failed: 'Failed', interrupted: 'Interrupted', cancelled: 'Cancelled' } as Record<string, string>
const RUN_LABEL = { queued: 'Queued', researching: 'Running', ...STATUS } as Record<string, string>
interface RunRow {
  id: string
  status: string
  started_at: string | null
}
const stamp = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : 'Queued'

export function ResultsStep({ research }: { research: Research }) {
  const qc = useQueryClient()
  const [sp, setSp] = useSearchParams()
  const runId = sp.get('run')
  const items = research.items.filter((i) => i.selected && i.latest_run)
  const [picked, setPicked] = useState(items[0]?.id)
  const viewQ = useQuery({
    queryKey: ['run', runId],
    queryFn: () => api.get<ItemRun & { item_id: string }>(`/runs/${runId}`),
    enabled: !!runId,
  })
  const cur = items.find((i) => i.id === (viewQ.data?.item_id ?? picked)) ?? items[0]
  // ponytail: a ?run= that is the latest run or belongs to another item is ignored
  const vd = viewQ.data
  const viewing = runId && vd && cur && vd.item_id === cur.id && vd.id !== cur.latest_run?.id ? vd : undefined
  const runsQ = useQuery({
    queryKey: ['item-runs', cur?.id, cur?.latest_run?.id],
    queryFn: () => api.get<RunRow[]>(`/items/${cur!.id}/runs`),
    enabled: !!cur,
  })
  const earlier = (Array.isArray(runsQ.data) ? runsQ.data : []).slice(1)
  const starredQ = useQuery({
    queryKey: ['manufacturers', 'starred'],
    queryFn: () => api.get<Manufacturer[]>('/manufacturers?starred=true&limit=200'),
    staleTime: Infinity,
  })
  const starred = (Array.isArray(starredQ.data) ? starredQ.data : []).map((m) => normName(m.name))
  const retry = useMutation({
    mutationFn: (id: string) => api.post(`/items/${id}/retry`),
    onSettled: () => qc.invalidateQueries({ queryKey: researchKey(research.id) }),
  })
  const run = viewing ?? cur?.latest_run
  const setRun = (id: string) => setSp(id ? { run: id } : {})
  return (
    <div className="view wrap">
      <h1>Results</h1>
      <div className="tabs" role="tablist">
        {items.map((i) => (
          <button
            key={i.id}
            role="tab"
            aria-selected={i.id === cur?.id}
            className={i.id === cur?.id ? 'on' : ''}
            onClick={() => {
              setPicked(i.id)
              setSp({})
            }}
          >
            {i.name}
            {i.latest_run!.status !== 'done' && (
              <small className="muted"> ({STATUS[i.latest_run!.status] ?? i.latest_run!.status})</small>
            )}
          </button>
        ))}
      </div>
      {(earlier.length > 0 || viewing) && (
        <p className="small">
          <label>
            Earlier runs{' '}
            <select value={viewing ? runId! : ''} onChange={(e) => setRun(e.target.value)}>
              <option value="">Latest</option>
              {earlier.map((r) => (
                <option key={r.id} value={r.id}>
                  {stamp(r.started_at)} ({RUN_LABEL[r.status] ?? 'Done'})
                </option>
              ))}
            </select>
          </label>
          {viewing && (
            <>
              {' '}
              <span className="muted">Viewing an earlier run</span> <Link to={{ search: '' }}>Back to latest</Link>
            </>
          )}
        </p>
      )}
      {runId && viewQ.isPending && <Spinner label="Loading run" />}
      {runId && viewQ.error && (
        <p className="field-error" role="alert">
          {viewQ.error.message} <Link to={{ search: '' }}>Back to latest</Link>
        </p>
      )}
      {cur &&
        run &&
        !(runId && viewQ.isPending) &&
        (run.status !== 'done' || !run.result ? (
          <>
            <div className="glass p">
              <p className="field-error">
                {run.status === 'interrupted'
                  ? 'Interrupted by a server restart'
                  : (run.error ?? STATUS[run.status] ?? 'No result')}
              </p>
              {!viewing && (
                <Button variant="ghost" onClick={() => retry.mutate(cur.id)} disabled={retry.isPending}>
                  Retry
                </Button>
              )}
              {retry.error && (
                <p className="field-error" role="alert">
                  {retry.error.message}
                </p>
              )}
            </div>
            {(run.status === 'queued' || run.status === 'researching') && <RetailCard retail={run.retail} running />}
          </>
        ) : (
          <div key={run.id}>
            <div className="two">
              <CostCard cost={run.result.cost} notes={run.result.notes} />
              <PurchaseCard result={run.result} units={run.result.quantity} starred={starred} />
            </div>
            <RetailCard retail={run.retail} running={false} />
            {!viewing && <SplitStrip item={cur} run={run} researchId={research.id} />}
          </div>
        ))}
    </div>
  )
}
