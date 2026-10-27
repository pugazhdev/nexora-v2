import { describe, expect, it } from 'vitest'
import { item, research, run } from './fixtures'
import { stepOf } from './useResearch'

describe('stepOf', () => {
  it('Select for several in-scope items with no run', () => {
    expect(stepOf(research([item({ id: 'a' }), item({ id: 'b' })]))).toBe('Select')
  })
  it('Details for a single in-scope item (out-of-scope ones do not count)', () => {
    expect(stepOf(research([item({ id: 'a' }), item({ id: 'b', in_scope: false, selected: false })]))).toBe('Details')
  })
  it('Research while any selected latest run is queued or researching', () => {
    const items = [item({ id: 'a', latest_run: run('done') }), item({ id: 'b', latest_run: run('queued') })]
    expect(stepOf(research(items))).toBe('Research')
    expect(stepOf(research([item({ latest_run: run('researching') })]))).toBe('Research')
  })
  it('Results when all selected latest runs are terminal; unselected runs ignored', () => {
    const items = [
      item({ id: 'a', latest_run: run('done') }),
      item({ id: 'b', latest_run: run('failed') }),
      item({ id: 'c', selected: false, latest_run: run('queued') }),
    ]
    expect(stepOf(research(items))).toBe('Results')
  })
})
