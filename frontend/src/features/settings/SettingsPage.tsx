import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { AppSettings } from '@/api/types'
import { Spinner } from '@/components/ui/Spinner'
import { Tag } from '@/components/ui/Tag'

const status = (ok: boolean) => <Tag tone={ok ? 'ok' : 'warn'}>{ok ? 'Configured' : 'Not configured'}</Tag>
const label = (k: string) => k.replace(/^budget_/, '').replace(/_/g, ' ')

function Rows({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <table className="tbl">
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <th scope="row">{k}</th>
            <td>{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function SettingsPage() {
  const q = useQuery({ queryKey: ['settings'], queryFn: () => api.get<AppSettings>('/settings') })
  const s = q.data
  return (
    <div className="view narrow">
      <h1>Settings</h1>
      {q.isPending && <Spinner label="Loading settings" />}
      {q.isError && (
        <p className="field-error" role="alert">
          {q.error.message}
        </p>
      )}
      {s && (
        <div className="glass p">
          <Rows
            rows={[
              ['OpenAI', status(s.openai_configured)],
              ['Tavily', status(s.tavily_configured)],
              ['Model', s.model],
              ['Vision model', s.vision_model],
              ['Research concurrency', s.research_concurrency],
            ]}
          />
          <h2>Budgets</h2>
          <Rows rows={Object.entries(s.budgets).map(([k, v]) => [label(k), v])} />
          <h2>Blocked sites</h2>
          <div className="parts">
            {s.denylist.map((d) => (
              <Tag key={d}>{d}</Tag>
            ))}
          </div>
          <p className="muted small">Edit backend/.env and restart to change these.</p>
        </div>
      )}
    </div>
  )
}
