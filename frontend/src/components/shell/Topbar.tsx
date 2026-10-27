import type { ReactNode } from 'react'
import { StepBar } from './StepBar'
import type { StepName } from './steps'

/** Breadcrumb left, step bar right (mockup .topbar). */
export function Topbar({
  crumb,
  steps,
  current,
  onSelect,
  locked,
}: {
  crumb: ReactNode
  steps: StepName[]
  current: StepName
  onSelect?: (s: StepName) => void
  locked?: StepName[]
}) {
  return (
    <div className="topbar">
      <div className="crumb">{crumb}</div>
      <StepBar steps={steps} current={current} onSelect={onSelect ?? (() => {})} locked={locked} />
    </div>
  )
}
