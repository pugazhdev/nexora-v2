import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SettingsPage } from './SettingsPage'

afterEach(() => vi.unstubAllGlobals())
const s = { openai_configured: false, tavily_configured: true, model: 'gpt-x', vision_model: 'gpt-v',
  budgets: { budget_search_calls: 12 }, research_concurrency: 2, denylist: ['amazon.in'] }

describe('SettingsPage', () => {
  it('shows configured state, models, budgets, denylist, env hint', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(s))))
    render(<QueryClientProvider client={new QueryClient()}><SettingsPage /></QueryClientProvider>)
    expect(await screen.findByText('Not configured')).toBeInTheDocument()
    expect(screen.getByText('Configured')).toBeInTheDocument()
    expect(screen.getByText('gpt-x')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('amazon.in')).toBeInTheDocument()
    expect(screen.getByText('Edit backend/.env and restart to change these.')).toBeInTheDocument()
  })
})
