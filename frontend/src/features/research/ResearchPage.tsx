import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Topbar } from '@/components/shell/Topbar'
import { stepsFor, type StepName } from '@/components/shell/steps'
import { Spinner } from '@/components/ui/Spinner'
import { Placeholder } from '@/pages/Placeholder'
import { ResultsStep } from '../results/ResultsStep'
import { DetailsStep } from './DetailsStep'
import { ResearchStep } from './ResearchStep'
import { SelectStep } from './SelectStep'
import { stepOf, useResearch } from './useResearch'

export function ResearchPage() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const { data, error } = useResearch(id)
  const [picked, setPicked] = useState(false)
  const [view, setView] = useState<StepName | null>(null) // a done step the user clicked back to
  const derived = data ? stepOf(data) : null
  // A new derived step (e.g. Start succeeded) wins over a view the user had clicked back to.
  const [seen, setSeen] = useState(derived)
  if (derived !== seen) {
    setSeen(derived)
    setView(null)
  }
  if (error)
    return (
      <div className="view narrow">
        <p className="field-error" role="alert">
          {error.message}
        </p>
      </div>
    )
  if (!data)
    return (
      <div className="view narrow">
        <Spinner />
      </div>
    )
  const latest = (derived === 'Select' && picked ? 'Details' : derived) as StepName
  const current = view ?? latest
  const steps = stepsFor(data.items.filter((i) => i.in_scope).length)
  return (
    <>
      <Topbar
        crumb={
          <>
            Research / <b>{data.title}</b>
          </>
        }
        steps={steps}
        current={current}
        locked={['Input']}
        onSelect={setView}
      />
      {current === 'Select' ? (
        <SelectStep
          research={data}
          onContinue={() => {
            setPicked(true)
            setView(null)
          }}
          onBack={() => nav('/')}
        />
      ) : current === 'Details' ? (
        <DetailsStep research={data} onBack={() => (derived === 'Select' ? setView('Select') : nav('/'))} />
      ) : current === 'Research' ? (
        <ResearchStep research={data} />
      ) : current === 'Results' ? (
        <ResultsStep research={data} />
      ) : (
        <Placeholder title={current} />
      )}
    </>
  )
}
