import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Question } from '@/api/types'
import { QuestionField } from './QuestionField'

const q = (o: Partial<Question>): Question => ({
  key: 'k',
  label: 'Label',
  help: null,
  kind: 'text',
  options: [],
  unit: null,
  min: null,
  max: null,
  default: null,
  required: true,
  price_relevant: true,
  ...o,
})
const opts = [
  { value: 'a', label: 'A' },
  { value: 'b', label: 'B' },
]

describe('QuestionField', () => {
  it('single: segmented buttons, click picks', async () => {
    const f = vi.fn()
    render(<QuestionField question={q({ kind: 'single', options: opts })} value="a" onChange={f} />)
    expect(screen.getByRole('button', { name: 'A' })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'B' }))
    expect(f).toHaveBeenCalledWith('b')
  })

  it('multi: toggles chips', async () => {
    const f = vi.fn()
    render(<QuestionField question={q({ kind: 'multi', options: opts })} value={['a']} onChange={f} />)
    await userEvent.click(screen.getByRole('button', { name: 'B' }))
    expect(f).toHaveBeenCalledWith(['a', 'b'])
    await userEvent.click(screen.getByRole('button', { name: 'A' }))
    expect(f).toHaveBeenLastCalledWith([])
  })

  it('number: Indian grouping, unit suffix, number value, empty is null, junk ignored', async () => {
    const f = vi.fn()
    render(<QuestionField question={q({ kind: 'number', unit: 'units' })} value={100000} onChange={f} />)
    const box = screen.getByRole('textbox', { name: 'Label' })
    expect(box).toHaveValue('1,00,000')
    expect(screen.getByText('units')).toBeInTheDocument()
    await userEvent.clear(box)
    expect(f).toHaveBeenLastCalledWith(null)
    await userEvent.type(box, '12ab3456')
    expect(box).toHaveValue('1,23,456')
    expect(f).toHaveBeenLastCalledWith(123456)
  })

  it('text and boolean', async () => {
    const f = vi.fn()
    const { unmount } = render(<QuestionField question={q({ kind: 'text' })} value="" onChange={f} />)
    await userEvent.type(screen.getByRole('textbox', { name: 'Label' }), 'x')
    expect(f).toHaveBeenCalledWith('x')
    unmount()
    render(<QuestionField question={q({ kind: 'boolean', label: 'Sterile?' })} value={false} onChange={f} />)
    await userEvent.click(screen.getByRole('switch', { name: 'Sterile?' }))
    expect(f).toHaveBeenLastCalledWith(true)
  })

  it('shows help and error; unknown kind renders nothing', () => {
    const { container, rerender } = render(
      <QuestionField question={q({ help: 'Hint' })} value="" error="Required" onChange={() => {}} />,
    )
    expect(screen.getByText('Hint')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Required')
    rerender(<QuestionField question={q({ kind: 'weird' as never })} value="" onChange={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })
})
