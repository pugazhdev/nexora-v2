import clsx from 'clsx'
import type { StepName } from './steps'

export function StepBar({
  steps,
  current,
  onSelect,
  locked = [],
}: {
  steps: StepName[]
  current: StepName
  onSelect: (s: StepName) => void
  locked?: StepName[]
}) {
  const at = steps.indexOf(current)
  return (
    <ol className="steps" aria-label="Progress">
      {steps.map((s, i) => {
        const done = i < at
        const on = i === at
        const inner = (
          <>
            <span className="n">{done ? '✓' : i + 1}</span>
            {s}
          </>
        )
        return (
          <li key={s} aria-current={on ? 'step' : undefined}>
            {done && !locked.includes(s) ? (
              <button type="button" className="step done" onClick={() => onSelect(s)}>
                {inner}
              </button>
            ) : (
              <span className={clsx('step', on && 'on', done && 'done')}>{inner}</span>
            )}
          </li>
        )
      })}
    </ol>
  )
}
