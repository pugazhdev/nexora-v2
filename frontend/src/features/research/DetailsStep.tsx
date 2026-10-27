import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { ApiError, api } from '@/api/client'
import type { Research, ResearchItem } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { Glass } from '@/components/ui/Glass'
import { QuestionField, type Answer } from './QuestionField'
import { researchKey, usePatchItem } from './useResearch'

type Answers = ResearchItem['answers']
type Errors = Record<string, Record<string, string>>

/** Stored answers plus defaults for unanswered questions that have one. */
function withDefaults(i: ResearchItem): Answers {
  const a = { ...i.answers }
  for (const q of i.questions) if (!(q.key in a) && q.default !== null) a[q.key] = q.default
  return a
}

/** "Name (picked option, switched-on flag)" for the summary line. */
function titleOf(i: ResearchItem, a: Answers): string {
  const bits = i.questions.flatMap((q) => {
    const v = a[q.key]
    if (q.kind === 'single') return q.options.filter((o) => o.value === v).map((o) => o.label)
    if (q.kind === 'boolean' && v === true) return [q.label.replace(/\?$/, '').toLowerCase()]
    return []
  })
  return bits.length ? `${i.name} (${bits.join(', ')})` : i.name
}

const DEBOUNCE_MS = 400

export function DetailsStep({ research, onBack }: { research: Research; onBack: () => void }) {
  const items = research.items.filter((i) => i.in_scope && i.selected)
  const qc = useQueryClient()
  const patch = usePatchItem(research.id)
  const [answers, setAnswers] = useState<Record<string, Answers>>(() =>
    Object.fromEntries(items.map((i) => [i.id, withDefaults(i)])),
  )
  const [dirty, setDirty] = useState<Record<string, boolean>>({}) // edits the server does not hold yet
  const [saveErrors, setSaveErrors] = useState<Record<string, string>>({})
  const [startErrors, setStartErrors] = useState<Errors>({})
  const [startMsg, setStartMsg] = useState<string | null>(null)
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  const inflight = useRef<Record<string, boolean>>({})
  const queued = useRef<Record<string, boolean>>({})
  const latest = useRef(answers)

  // At most one PATCH per item in flight; an edit meanwhile queues one more with the latest answers.
  const flush = (id: string) => {
    clearTimeout(timers.current[id])
    delete timers.current[id]
    if (inflight.current[id]) {
      queued.current[id] = true
      return
    }
    inflight.current[id] = true
    const sent = latest.current[id]
    patch
      .mutateAsync({ itemId: id, answers: sent })
      .then(() => {
        if (sent !== latest.current[id]) return // newer edit still to send
        setDirty((d) => ({ ...d, [id]: false }))
        setSaveErrors((e) => ({ ...e, [id]: '' }))
      })
      .catch((e: Error) => setSaveErrors((x) => ({ ...x, [id]: e.message })))
      .finally(() => {
        inflight.current[id] = false
        if (queued.current[id]) {
          queued.current[id] = false
          flush(id)
        }
      })
  }
  const save = (id: string, a: Answers, wait = DEBOUNCE_MS) => {
    latest.current = { ...latest.current, [id]: a }
    setDirty((d) => ({ ...d, [id]: true }))
    clearTimeout(timers.current[id])
    timers.current[id] = setTimeout(() => flush(id), wait)
  }

  // Save defaults once so the server validates them; flush any pending edit on leave.
  useEffect(() => {
    for (const i of items) {
      if (Object.keys(answers[i.id] ?? {}).length !== Object.keys(i.answers).length) save(i.id, answers[i.id]!, 0)
    }
    const t = timers.current
    return () => {
      for (const id of Object.keys(t)) flush(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const change = (i: ResearchItem, key: string, v: Answer | null) => {
    const next = { ...answers[i.id] } as Answers
    if (v === null) delete next[key]
    else next[key] = v
    setAnswers({ ...answers, [i.id]: next })
    setStartErrors((e) => {
      const rest = { ...e[i.id] }
      delete rest[key]
      return { ...e, [i.id]: rest }
    })
    save(i.id, next)
  }

  const run = useMutation({
    mutationFn: () => api.post(`/research/${research.id}/start`),
    onSuccess: () => qc.invalidateQueries({ queryKey: researchKey(research.id) }),
    onError: (e) => {
      const err = e as ApiError
      if (err.status === 409) return qc.invalidateQueries({ queryKey: researchKey(research.id) })
      const byItem = (err.details as { items?: Errors } | null)?.items
      if (err.status === 400 && byItem) return setStartErrors(byItem)
      setStartMsg(err.message)
    },
  })

  const errorOf = (i: ResearchItem, key: string) => startErrors[i.id]?.[key] ?? i.answer_errors[key]
  const hasErrors = items.some(
    (i) => Object.keys(i.answer_errors).length > 0 || Object.keys(startErrors[i.id] ?? {}).length > 0,
  )
  const n = items.length

  return (
    <div className="view narrow">
      <h1>Details</h1>
      <div className="muted">Only what we could not read from the photo.</div>
      {items.map((i) => {
        const a = answers[i.id] ?? {}
        const complete = i.questions.length === 1 && i.questions[0]!.key === 'quantity' && a.quantity != null
        return (
          <Glass key={i.id} className="p details-card">
            <h2>
              {i.name}
              {complete && <span className="tag tag-ok">Looks complete</span>}
            </h2>
            {i.questions.map((q) => (
              <QuestionField
                key={q.key}
                question={q}
                value={a[q.key]}
                error={errorOf(i, q.key)}
                onChange={(v) => change(i, q.key, v)}
              />
            ))}
            {saveErrors[i.id] && (
              <p className="field-error" role="alert">
                {saveErrors[i.id]}{' '}
                <Button variant="ghost" onClick={() => flush(i.id)}>
                  Retry
                </Button>
              </p>
            )}
          </Glass>
        )
      })}
      <div className="summary">
        <span>
          Research{' '}
          <b>
            {n} {n === 1 ? 'item' : 'items'}
          </b>
          : {items.map((i) => titleOf(i, answers[i.id] ?? {})).join(', ')}
        </span>
        <Button variant="ghost" onClick={onBack}>
          Back
        </Button>
        <Button
          disabled={n === 0 || items.some((i) => dirty[i.id]) || hasErrors || run.isPending}
          onClick={() => {
            setStartMsg(null)
            run.mutate()
          }}
        >
          Start research
        </Button>
      </div>
      {startMsg && (
        <p className="field-error" role="alert">
          {startMsg}
        </p>
      )}
    </div>
  )
}
