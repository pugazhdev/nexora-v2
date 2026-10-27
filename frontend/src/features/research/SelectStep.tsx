import type { Research } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { Glass } from '@/components/ui/Glass'
import { usePatchItem } from './useResearch'

export function SelectStep({
  research,
  onContinue,
  onBack,
}: {
  research: Research
  onContinue: () => void
  onBack: () => void
}) {
  const patch = usePatchItem(research.id)
  const n = research.items.filter((i) => i.in_scope).length
  const ticked = research.items.filter((i) => i.selected).length
  return (
    <div className="view narrow">
      <h1>
        {n} {n === 1 ? 'item' : 'items'} found
      </h1>
      <div className="muted">Pick what to research. Each one runs in turn.</div>
      <Glass className="p picks">
        {research.items.map((i) => (
          <label key={i.id} className={`pick${i.selected ? ' on' : ''}${i.in_scope ? '' : ' off'}`}>
            <input
              type="checkbox"
              checked={i.selected}
              disabled={!i.in_scope}
              onChange={(e) => patch.mutate({ itemId: i.id, selected: e.target.checked })}
            />
            <span className="name">{i.name}</span>
            <span className="meta">{i.in_scope ? i.image_region_hint : i.scope_reason}</span>
          </label>
        ))}
      </Glass>
      {patch.error && (
        <p className="field-error" role="alert">
          {patch.error.message}
        </p>
      )}
      <div className="actions">
        <Button variant="ghost" onClick={onBack}>
          Back
        </Button>
        <Button disabled={ticked === 0} onClick={onContinue}>
          Continue
        </Button>
      </div>
    </div>
  )
}
