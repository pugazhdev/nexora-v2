import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { StepBar } from './StepBar'
import { stepsFor } from './steps'

const all = stepsFor(2)

describe('StepBar', () => {
  it('marks done steps as buttons and the current step with aria-current', () => {
    render(<StepBar steps={all} current="Details" onSelect={() => {}} />)
    expect(screen.getByRole('button', { name: /Input/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Select/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Details/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Results/ })).toBeNull()
    expect(screen.getByText('Details').closest('[aria-current="step"]')).not.toBeNull()
  })

  it('calls onSelect only for done steps', async () => {
    const onSelect = vi.fn()
    render(<StepBar steps={all} current="Details" onSelect={onSelect} />)
    await userEvent.click(screen.getByText('Results'))
    await userEvent.click(screen.getByText('Details'))
    expect(onSelect).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: /Select/ }))
    expect(onSelect).toHaveBeenCalledWith('Select')
  })

  it('hides Select for a single item', () => {
    expect(stepsFor(1)).toEqual(['Input', 'Details', 'Research', 'Results'])
    render(<StepBar steps={stepsFor(1)} current="Input" onSelect={() => {}} />)
    expect(screen.queryByText('Select')).toBeNull()
  })
})
