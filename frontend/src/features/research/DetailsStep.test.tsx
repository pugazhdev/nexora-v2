import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Question, Research } from '@/api/types'
import { DetailsStep } from './DetailsStep'
import { item, research } from './fixtures'

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status })
const err = (status: number, code: string, message: string, details: unknown = {}) =>
  json({ error: { code, message, details } }, status)

const qty: Question = {
  key: 'quantity', label: 'Quantity', help: null, kind: 'number', options: [], unit: 'units',
  min: 1, max: null, default: null, required: true, price_relevant: true,
}
const size: Question = {
  key: 'size', label: 'Size', help: null, kind: 'single', options: [{ value: 's', label: 'Small' }, { value: 'l', label: 'Large' }],
  unit: null, min: null, max: null, default: 'l', required: true, price_relevant: true,
}
const sterile: Question = { ...size, key: 'sterile', label: 'Sterile?', kind: 'boolean', options: [], default: null }

function setup(r: Research, handler: (url: string, init: RequestInit) => Response | Promise<Response> = () => json({})) {
  const fetchMock = vi.fn(async (u: string, init: RequestInit = {}) => handler(u, init))
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  qc.setQueryData(['research', 'r1'], r)
  const onBack = vi.fn()
  render(
    <QueryClientProvider client={qc}>
      <DetailsStep research={r} onBack={onBack} />
    </QueryClientProvider>,
  )
  const calls = (m: string) => fetchMock.mock.calls.filter(([, i]) => i?.method === m)
  return { fetchMock, calls, onBack, qc }
}
const start = () => screen.getByRole('button', { name: 'Start research' })

afterEach(() => vi.unstubAllGlobals())

describe('DetailsStep', () => {
  it('shows only selected in-scope items, summary line, and Looks complete for quantity only', () => {
    setup(
      research([
        item({ id: 'a', name: 'Mask', questions: [qty], answers: { quantity: 100000 } }),
        item({ id: 'b', name: 'Syringe', questions: [qty, sterile], answers: { quantity: 5, sterile: true } }),
        item({ id: 'c', name: 'Gloves', selected: false, questions: [qty] }),
        item({ id: 'd', name: 'Pills', in_scope: false, questions: [qty] }),
      ]),
    )
    expect(screen.getByRole('heading', { name: /^Mask/ })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Gloves' })).toBeNull()
    expect(screen.queryByRole('heading', { name: 'Pills' })).toBeNull()
    expect(screen.getAllByText('Looks complete')).toHaveLength(1)
    expect(screen.getAllByRole('textbox')[0]).toHaveValue('1,00,000')
    expect(screen.getByText(/Research/, { selector: '.summary span' })).toHaveTextContent(
      'Research 2 items: Mask, Syringe (sterile)',
    )
  })

  it('shows server answer errors and disables Start; enabled when clean', () => {
    setup(research([item({ questions: [qty], answers: {}, answer_errors: { quantity: 'Quantity is required' } })]))
    expect(screen.getByRole('alert')).toHaveTextContent('Quantity is required')
    expect(start()).toBeDisabled()
  })

  it('enables Start when clean and POSTs /start', async () => {
    const { calls } = setup(research([item({ questions: [qty], answers: { quantity: 5 } })]))
    expect(start()).toBeEnabled()
    await userEvent.click(start())
    await waitFor(() => expect(calls('POST')).toHaveLength(1))
    expect(calls('POST')[0]![0]).toBe('/api/research/r1/start')
  })

  it('debounces answer PATCHes, includes defaults in the first one, disables Start meanwhile', async () => {
    const { calls } = setup(
      research([item({ id: 'a', questions: [size, qty], answers: { quantity: 5 } })]),
      (_u, init) => json(item({ id: 'a', answers: JSON.parse(String(init.body)).answers })),
    )
    // default for size is saved with the first PATCH
    await waitFor(() => expect(calls('PATCH')).toHaveLength(1))
    expect(JSON.parse(String(calls('PATCH')[0]![1]!.body))).toEqual({ answers: { quantity: 5, size: 'l' } })
    expect(screen.getByRole('button', { name: 'Large' })).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => expect(start()).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Small' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Quantity' }), '0')
    expect(start()).toBeDisabled()
    await waitFor(() => expect(calls('PATCH')).toHaveLength(2))
    expect(JSON.parse(String(calls('PATCH')[1]![1]!.body))).toEqual({ answers: { quantity: 50, size: 's' } })
  })

  it('failed PATCH keeps Start disabled, shows the error; Retry success enables Start', async () => {
    let fail = true
    const { calls } = setup(research([item({ id: 'a', questions: [qty], answers: { quantity: 5 } })]), () =>
      fail ? err(500, 'boom', 'Save failed') : json(item({ id: 'a' })),
    )
    await userEvent.type(screen.getByRole('textbox', { name: 'Quantity' }), '0')
    expect(await screen.findByText(/Save failed/)).toBeInTheDocument()
    expect(start()).toBeDisabled()
    fail = false
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(start()).toBeEnabled())
    expect(JSON.parse(String(calls('PATCH')[1]![1]!.body))).toEqual({ answers: { quantity: 50 } })
  })

  it('sends one PATCH at a time per item, the second only after the first settles, with latest answers', async () => {
    const gates: ((r: Response) => void)[] = []
    const { calls } = setup(
      research([item({ id: 'a', questions: [qty], answers: { quantity: 5 } })]),
      () => new Promise<Response>((res) => gates.push(res)),
    )
    const box = screen.getByRole('textbox', { name: 'Quantity' })
    await userEvent.type(box, '0')
    await waitFor(() => expect(calls('PATCH')).toHaveLength(1))
    await userEvent.type(box, '0')
    await new Promise((r) => setTimeout(r, 500)) // debounce elapsed while first is in flight
    expect(calls('PATCH')).toHaveLength(1)
    gates[0]!(json(item({ id: 'a' })))
    await waitFor(() => expect(calls('PATCH')).toHaveLength(2))
    expect(JSON.parse(String(calls('PATCH')[1]![1]!.body))).toEqual({ answers: { quantity: 500 } })
    expect(start()).toBeDisabled()
    gates[1]!(json(item({ id: 'a' })))
    await waitFor(() => expect(start()).toBeEnabled())
  })

  it('editing one field clears only that field start error', async () => {
    setup(
      research([item({ id: 'a', questions: [qty, { ...qty, key: 'x', label: 'Other' }], answers: { quantity: 5, x: 1 } })]),
      (u) =>
        u.endsWith('/start')
          ? err(400, 'invalid', 'Bad', { items: { a: { quantity: 'Q bad', x: 'X bad' } } })
          : json(item({ id: 'a' })),
    )
    await userEvent.click(start())
    await screen.findByText('Q bad')
    await userEvent.type(screen.getByRole('textbox', { name: 'Quantity' }), '1')
    expect(screen.queryByText('Q bad')).toBeNull()
    expect(screen.getByText('X bad')).toBeInTheDocument()
  })

  it('maps 400 details.items onto fields', async () => {
    setup(research([item({ id: 'a', questions: [qty], answers: { quantity: 5 } })]), () =>
      err(400, 'invalid', 'Bad', { items: { a: { quantity: 'Must be at least 100' } } }),
    )
    await userEvent.click(start())
    expect(await screen.findByText('Must be at least 100')).toBeInTheDocument()
    expect(start()).toBeDisabled()
  })

  it('shows the server message on 503', async () => {
    setup(research([item({ questions: [qty], answers: { quantity: 5 } })]), () =>
      err(503, 'config_missing', 'Set OPENAI_API_KEY, OPENAI_MODEL and OPENAI_VISION_MODEL in backend/.env'),
    )
    await userEvent.click(start())
    expect(await screen.findByText(/Set OPENAI_API_KEY/)).toBeInTheDocument()
  })

  it('refetches on 409', async () => {
    const { qc } = setup(research([item({ questions: [qty], answers: { quantity: 5 } })]), () =>
      err(409, 'conflict', 'Already running'),
    )
    const spy = vi.spyOn(qc, 'invalidateQueries')
    await userEvent.click(start())
    await waitFor(() => expect(spy).toHaveBeenCalled())
    expect(screen.queryByText('Already running')).toBeNull()
  })

  it('Back calls onBack', async () => {
    const { onBack } = setup(research([item({ questions: [qty], answers: { quantity: 5 } })]))
    await userEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(onBack).toHaveBeenCalled()
  })
})
