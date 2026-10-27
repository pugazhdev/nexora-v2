import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import type { RunEvent, RunSnapshot } from '@/api/types'
import { researchKey } from './useResearch'

const LIVE = ['queued', 'researching']

/** Live step log for a research. `done`: every selected run is terminal, so never reconnect. */
export function useRunEvents(researchId: string, done: boolean) {
  const qc = useQueryClient()
  const [state, setState] = useState<{ id: string; list: RunEvent[] }>({ id: researchId, list: [] })
  useEffect(() => {
    let cursor = 0
    let es: EventSource | null = null
    let stopped = done
    const open = () => {
      es = new EventSource(`/api/research/${researchId}/events?after=${cursor}`)
      es.addEventListener('step', (m) => {
        const e = JSON.parse((m as MessageEvent).data) as RunEvent
        cursor = Math.max(cursor, e.id)
        setState((s) => {
          const list = s.id === researchId ? s.list : [] // new research: drop the old log
          return { id: researchId, list: list.some((p) => p.id === e.id) ? list : [...list, e] }
        })
      })
      es.addEventListener('status', (m) => {
        const s = JSON.parse((m as MessageEvent).data) as RunSnapshot
        qc.invalidateQueries({ queryKey: researchKey(researchId) })
        if (s.items.every((i) => !LIVE.includes(i.status))) {
          stopped = true
          es?.close()
        }
      })
      es.onerror = () => {
        if (stopped) es?.close()
        else if (es?.readyState === 2) open() // browser gave up; resume from the cursor
      }
    }
    open()
    return () => {
      stopped = true
      es?.close()
    }
  }, [researchId, done, qc])
  return state.id === researchId ? state.list : []
}
