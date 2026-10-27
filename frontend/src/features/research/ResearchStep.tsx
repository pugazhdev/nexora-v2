import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '@/api/client'
import type { Research } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { Tag } from '@/components/ui/Tag'
import { researchKey } from './useResearch'
import { useRunEvents } from './useRunEvents'

const LIVE = ['queued', 'researching']

export function ResearchStep({ research }: { research: Research }) {
  const qc = useQueryClient()
  const items = research.items.filter((i) => i.selected && i.latest_run)
  const done = items.every((i) => !LIVE.includes(i.latest_run!.status))
  const events = useRunEvents(research.id, done)
  const refresh = () => qc.invalidateQueries({ queryKey: researchKey(research.id) })
  const cancel = useMutation({ mutationFn: () => api.post(`/research/${research.id}/cancel`), onSettled: refresh })
  const retry = useMutation({ mutationFn: (id: string) => api.post(`/items/${id}/retry`), onSettled: refresh })

  const current = items.find((i) => i.latest_run!.status === 'researching') ?? items.find((i) => LIVE.includes(i.latest_run!.status)) ?? items[items.length - 1]
  const log = events.filter((e) => e.run_id === current?.latest_run?.id)
  const finished = items.filter((i) => !LIVE.includes(i.latest_run!.status)).length
  const running = current && current.latest_run!.status === 'researching' ? Math.min(0.9, log.length / 10) : 0
  const raw = items.length ? Math.round(((finished + running) / items.length) * 100) : 0
  // never shows a lower percentage while the page is open (a retry makes a finished item live again)
  const [hw, setHw] = useState({ id: research.id, v: 0 })
  const pct = Math.max(hw.id === research.id ? hw.v : 0, raw)
  if (hw.id !== research.id || pct > hw.v) setHw({ id: research.id, v: pct })

  return (
    <div className="view narrow">
      <h1>Researching</h1>
      <div className="muted">You can leave this page. It keeps running and shows up in Today.</div>
      <div className="research">
        <div className="glass p queue">
          {items.map((i, n) => {
            const r = i.latest_run!
            return (
              <div key={i.id} className={`item${i === current ? ' now' : ''}`}>
                {r.status === 'done' ? <span className="s ok" aria-hidden /> : r.status === 'researching' ? <Spinner label="Running" /> : <span className="s" aria-hidden />}
                <span>{i.name}</span>
                <span className="muted">
                  {r.status === 'researching' ? `${n + 1} of ${items.length}` : r.status === 'queued' ? 'waiting' : r.status === 'done' ? 'done' : r.status === 'cancelled' ? 'Cancelled' : ''}
                </span>
                {(r.status === 'failed' || r.status === 'interrupted') && (
                  <>
                    <span className="field-error">{r.status === 'interrupted' ? 'Interrupted by a server restart' : (r.error ?? 'Failed')}</span>
                    <Button variant="ghost" onClick={() => retry.mutate(i.id)}>
                      Retry
                    </Button>
                    {retry.error && retry.variables === i.id && (
                      <span className="field-error" role="alert">
                        {retry.error.message}
                      </span>
                    )}
                  </>
                )}
              </div>
            )
          })}
        </div>
        <div className="glass p">
          <h2>{current?.name}</h2>
          <div className="bar">
            <i style={{ width: `${pct}%` }} role="progressbar" aria-label="Research progress" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} />
          </div>
          <div className="log" role="log" aria-live="polite">
            {log.map((e) => (
              <div key={e.id} className="row">
                <span className="s ok" aria-hidden />
                <div>
                  {e.message}
                  {e.level !== 'info' && <Tag tone={e.level === 'error' ? 'bad' : 'warn'}>{e.level}</Tag>}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
      {!done && (
        <div className="actions">
          <Button variant="ghost" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
            Cancel
          </Button>
          {cancel.error && (
            <span className="field-error" role="alert">
              {cancel.error.message}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
