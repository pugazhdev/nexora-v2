import clsx from 'clsx'
import { useId, useState } from 'react'
import type { Question } from '@/api/types'

export type Answer = string | number | boolean | string[]

/** "100000" becomes "1,00,000"; keeps a trailing dot and the decimals while typing. */
function groupIndian(text: string): string {
  const [int = '', dec] = text.split('.')
  const grouped = int ? Number(int).toLocaleString('en-IN', { maximumFractionDigits: 0 }) : ''
  return dec === undefined ? grouped : `${grouped}.${dec}`
}

/** Keep digits and one dot only. */
const clean = (s: string) => {
  const t = s.replace(/[^\d.]/g, '')
  const i = t.indexOf('.')
  return i < 0 ? t : t.slice(0, i + 1) + t.slice(i + 1).replace(/\./g, '')
}

function NumberField({
  id,
  q,
  value,
  onChange,
}: {
  id: string
  q: Question
  value: unknown
  onChange: (v: Answer | null) => void
}) {
  const [text, setText] = useState(typeof value === 'number' ? groupIndian(String(value)) : '')
  return (
    <div className="field">
      <input
        id={id}
        inputMode="decimal"
        value={text}
        onChange={(e) => {
          const t = clean(e.target.value)
          setText(groupIndian(t))
          onChange(t === '' || t === '.' ? null : Number(t))
        }}
      />
      {q.unit && <span className="muted">{q.unit}</span>}
    </div>
  )
}

function Chips({
  labelId,
  options,
  isOn,
  onPick,
}: {
  labelId: string
  options: Question['options']
  isOn: (v: string) => boolean
  onPick: (v: string) => void
}) {
  return (
    <div className="seg" role="group" aria-labelledby={labelId}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={isOn(o.value)}
          className={clsx(isOn(o.value) && 'on')}
          onClick={() => onPick(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** One control per question kind. Unknown kinds render nothing. */
export function QuestionField({
  question: q,
  value,
  error,
  onChange,
}: {
  question: Question
  value: unknown
  error?: string
  onChange: (v: Answer | null) => void
}) {
  const id = useId()
  const sel = Array.isArray(value) ? (value as string[]) : []
  let control = null
  if (q.kind === 'single')
    control = <Chips labelId={id} options={q.options} isOn={(v) => value === v} onPick={onChange} />
  else if (q.kind === 'multi')
    control = (
      <Chips
        labelId={id}
        options={q.options}
        isOn={(v) => sel.includes(v)}
        onPick={(v) => onChange(sel.includes(v) ? sel.filter((x) => x !== v) : [...sel, v])}
      />
    )
  else if (q.kind === 'number') control = <NumberField id={id + 'f'} q={q} value={value} onChange={onChange} />
  else if (q.kind === 'text')
    control = (
      <div className="field">
        <input id={id + 'f'} value={typeof value === 'string' ? value : ''} onChange={(e) => onChange(e.target.value)} />
      </div>
    )
  else if (q.kind === 'boolean')
    control = (
      <button
        type="button"
        role="switch"
        aria-checked={value === true}
        aria-labelledby={id}
        className={clsx('switch', value === true && 'on')}
        onClick={() => onChange(value !== true)}
      />
    )
  if (!control) return null
  return (
    <div className="q">
      <div>
        <label id={id} htmlFor={q.kind === 'number' || q.kind === 'text' ? id + 'f' : undefined}>
          {q.label}
        </label>
        {q.help && <small className="muted">{q.help}</small>}
      </div>
      <div>
        {control}
        {error && (
          <p className="field-error q-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  )
}
