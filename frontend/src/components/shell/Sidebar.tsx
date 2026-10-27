import { useQuery } from '@tanstack/react-query'
import { Bookmark, Clock, Factory, Plus, Search, Settings } from 'lucide-react'
import { useMemo, type ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { DeleteResearch } from '@/components/shell/DeleteResearch'
import { Spinner } from '@/components/ui/Spinner'
import type { ResearchSummary } from '@/api/types'

const DAY = 86400000
const icon = (I: typeof Search) => <I className="i" aria-hidden="true" />

function Item({ to, icon, count, children }: { to: string; icon: ReactNode; count?: number; children: ReactNode }) {
  return (
    <NavLink to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'on' : '')}>
      {icon}
      {children}
      {count !== undefined && <span className="count">{count}</span>}
    </NavLink>
  )
}

function Group({ title, rows }: { title: string; rows: ResearchSummary[] }) {
  if (!rows.length) return null
  return (
    <div>
      <div className="group">{title}</div>
      <div className="recent">
        {rows.map((r) => (
          <DeleteResearch key={r.id} id={r.id} title={r.title}>
            <NavLink to={`/research/${r.id}`} className={({ isActive }) => (isActive ? 'on' : '')}>
              <span className={r.status === 'researching' ? 'dot dot-run' : 'dot'} aria-hidden="true" />
              {r.title}
            </NavLink>
          </DeleteResearch>
        ))}
      </div>
    </div>
  )
}

export function Sidebar() {
  const navigate = useNavigate()
  const research = useQuery({
    queryKey: ['research', 'recent'],
    queryFn: () => api.get<ResearchSummary[]>('/research?limit=20'),
  })
  const makers = useQuery({
    queryKey: ['manufacturers', 'count'],
    queryFn: () => api.get<{ total: number; starred: number }>('/manufacturers/count'),
  })

  const { today, week } = useMemo(() => {
    const rows = research.data ?? []
    const now = research.dataUpdatedAt
    const start = new Date(now).setHours(0, 0, 0, 0)
    const time = (r: ResearchSummary) => new Date(r.created_at).getTime()
    return {
      today: rows.filter((r) => time(r) >= start),
      week: rows.filter((r) => time(r) < start && time(r) >= now - 7 * DAY),
    }
  }, [research.data, research.dataUpdatedAt])

  return (
    <aside className="glass side">
      <div className="brand">
        <div className="logo">
          <i />
        </div>
        Nexora
      </div>
      <button type="button" className="new" onClick={() => navigate('/')}>
        {icon(Plus)}
        New research
      </button>
      <nav className="nav" aria-label="Main">
        <Item to="/" icon={icon(Search)}>
          Research
        </Item>
        <Item to="/history" icon={icon(Clock)}>
          History
        </Item>
        <Item to="/manufacturers" icon={icon(Factory)} count={makers.data?.total}>
          Manufacturers
        </Item>
        <Item to="/shortlist" icon={icon(Bookmark)} count={makers.data?.starred}>
          Shortlist
        </Item>
      </nav>
      {research.isPending && (
        <div className="recent-state">
          <Spinner label="Loading recent research" />
        </div>
      )}
      {research.isError && (
        <div className="recent-state muted" role="alert">
          Could not load recent research
          <button type="button" className="btn btn-ghost" onClick={() => void research.refetch()}>
            Retry
          </button>
        </div>
      )}
      <Group title="Today" rows={today} />
      <Group title="This week" rows={week} />
      <div className="foot">
        <nav className="nav" aria-label="Settings" style={{ margin: 0 }}>
          <Item to="/settings" icon={icon(Settings)}>
            Settings
          </Item>
        </nav>
      </div>
    </aside>
  )
}
