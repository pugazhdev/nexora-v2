import { useInfiniteQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '@/api/client'
import type { ResearchSummary } from '@/api/types'
import { DeleteResearch } from '@/components/shell/DeleteResearch'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { Tag } from '@/components/ui/Tag'

const PAGE = 50
const STATUS = { draft: 'Draft', researching: 'Researching', done: 'Done' }
const when = (iso: string) =>
  new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit' })

export function HistoryPage() {
  const q = useInfiniteQuery({
    queryKey: ['research', 'history'],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => api.get<ResearchSummary[]>(`/research?limit=${PAGE}&offset=${pageParam}`),
    getNextPageParam: (last, all) => (last.length === PAGE ? all.length * PAGE : undefined),
  })
  const rows = [...new Map((q.data?.pages.flat() ?? []).map((r) => [r.id, r])).values()]
  return (
    <div className="view wrap">
      <h1>History</h1>
      {q.isPending && <Spinner label="Loading history" />}
      {q.isError && (
        <p className="field-error" role="alert">
          {q.error.message}
        </p>
      )}
      {q.isSuccess && !rows.length && <p className="muted">No research yet. Start one from New research.</p>}
      {rows.length > 0 && (
        <div className="glass p">
          <table className="tbl">
            <thead>
              <tr>
                <th>Title</th>
                <th>Date</th>
                <th className="r">Items</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>
                    <DeleteResearch id={r.id} title={r.title}>
                      <Link to={`/research/${r.id}`}>{r.title}</Link>
                    </DeleteResearch>
                  </td>
                  <td className="muted">{when(r.created_at)}</td>
                  <td className="r">{r.item_count}</td>
                  <td>
                    <Tag tone={r.status === 'done' ? 'ok' : 'neutral'}>{STATUS[r.status]}</Tag>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {q.hasNextPage && (
            <Button variant="ghost" onClick={() => void q.fetchNextPage()} disabled={q.isFetchingNextPage}>
              Load more
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
