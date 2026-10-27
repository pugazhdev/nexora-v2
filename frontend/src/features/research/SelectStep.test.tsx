import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { item, research } from './fixtures'
import { SelectStep } from './SelectStep'

const items = [
  item({ id: 'a', name: 'Surgical face mask' }),
  item({ id: 'b', name: 'Paracetamol', in_scope: false, selected: false, scope_reason: 'Medicines are out of scope' }),
]

function renderIt(r = research(items)) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  qc.setQueryData(['research', 'r1'], r)
  render(
    <QueryClientProvider client={qc}>
      <SelectStep research={r} onContinue={() => {}} onBack={() => {}} />
    </QueryClientProvider>,
  )
  return qc
}

afterEach(() => vi.unstubAllGlobals())

describe('SelectStep', () => {
  it('disables out-of-scope rows and shows the reason', () => {
    renderIt()
    expect(screen.getByRole('checkbox', { name: /Paracetamol/ })).toBeDisabled()
    expect(screen.getByText('Medicines are out of scope')).toBeInTheDocument()
    expect(screen.getByText('3-ply, ear loop')).toBeInTheDocument()
  })

  it('disables Continue when nothing is ticked', () => {
    renderIt(research([item({ selected: false }), item({ id: 'b', selected: false })]))
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
  })

  it('enables Continue when something is ticked', () => {
    renderIt()
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled()
  })
})
