import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { InputStep } from './InputStep'

function renderIt() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<InputStep />} />
          <Route path="/research/:id" element={<div>research page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
const reply = (status: number, body: unknown) =>
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  )

afterEach(() => vi.unstubAllGlobals())

describe('InputStep', () => {
  it('disables Analyse until there is input', async () => {
    renderIt()
    const btn = screen.getByRole('button', { name: 'Analyse' })
    expect(btn).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Requirement'), 'syringe')
    expect(btn).toBeEnabled()
  })

  it('shows the server error message', async () => {
    reply(400, { error: { code: 'bad_image', message: 'That image could not be read.', details: {} } })
    renderIt()
    await userEvent.type(screen.getByLabelText('Requirement'), 'syringe')
    await userEvent.click(screen.getByRole('button', { name: 'Analyse' }))
    expect(await screen.findByText('That image could not be read.')).toBeInTheDocument()
  })

  it('navigates when items come back', async () => {
    reply(200, { id: 'abc', message: null, items: [{ id: 'i', in_scope: true }] })
    renderIt()
    await userEvent.type(screen.getByLabelText('Requirement'), 'syringe')
    await userEvent.click(screen.getByRole('button', { name: 'Analyse' }))
    expect(await screen.findByText('research page')).toBeInTheDocument()
  })

  it('shows the message and stays when nothing is in scope', async () => {
    reply(200, { id: 'abc', message: 'The photo is too blurry to read.', items: [{ id: 'i', in_scope: false }] })
    renderIt()
    await userEvent.type(screen.getByLabelText('Requirement'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Analyse' }))
    expect(await screen.findByText('The photo is too blurry to read.')).toBeInTheDocument()
    expect(screen.queryByText('research page')).toBeNull()
  })

  it('rejects unsupported files inline', async () => {
    renderIt()
    const file = new File(['x'], 'a.gif', { type: 'image/gif' })
    await userEvent.upload(screen.getByLabelText('Choose an image'), file, { applyAccept: false })
    expect(await screen.findByText('Use a JPG, PNG or WebP image.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyse' })).toBeDisabled()
  })

  it('a stale file error does not mask a later server error', async () => {
    reply(400, { error: { code: 'x', message: 'Server says no.', details: {} } })
    renderIt()
    const file = new File(['x'], 'a.gif', { type: 'image/gif' })
    await userEvent.upload(screen.getByLabelText('Choose an image'), file, { applyAccept: false })
    expect(await screen.findByText('Use a JPG, PNG or WebP image.')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Requirement'), 'syringe')
    await userEvent.click(screen.getByRole('button', { name: 'Analyse' }))
    expect(await screen.findByText('Server says no.')).toBeInTheDocument()
    expect(screen.queryByText('Use a JPG, PNG or WebP image.')).toBeNull()
  })

  it('locks inputs while analysing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )
    renderIt()
    await userEvent.type(screen.getByLabelText('Requirement'), 'syringe')
    await userEvent.click(screen.getByRole('button', { name: 'Analyse' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /Analysing/ })).toBeDisabled())
    expect(screen.getByLabelText('Requirement')).toBeDisabled()
    expect(screen.getByText('Reading the photo and requirement')).toBeInTheDocument()
  })
})
