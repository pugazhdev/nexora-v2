import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Star } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { Manufacturer } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { Tag } from '@/components/ui/Tag'

const PAGE = 50
const day = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '-'

/** /shortlist renders this with starred set. */
export function ManufacturersPage({ starred = false }: { starred?: boolean }) {
  const qc = useQueryClient()
  const [text, setText] = useState('')
  const [q, setQ] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setQ(text.trim()), 300)
    return () => clearTimeout(t)
  }, [text])
  const list = useInfiniteQuery({
    queryKey: ['manufacturers', 'list', starred, q],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => {
      const params = [starred && 'starred=true', q && `q=${encodeURIComponent(q)}`, `limit=${PAGE}`, `offset=${pageParam}`]
      return api.get<Manufacturer[]>(`/manufacturers?${params.filter(Boolean).join('&')}`)
    },
    getNextPageParam: (last, all) => (last.length === PAGE ? all.length * PAGE : undefined),
    placeholderData: (prev) => prev,
  })
  const star = useMutation({
    mutationFn: (m: Manufacturer) => api.patch<Manufacturer>(`/manufacturers/${m.id}`, { starred: !m.starred }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['manufacturers'] }),
  })
  const rows = [...new Map((list.data?.pages.flat() ?? []).map((m) => [m.id, m])).values()]
  return (
    <div className="view wrap">
      <h1>{starred ? 'Shortlist' : 'Manufacturers'}</h1>
      <input
        type="search"
        className="search"
        placeholder="Search by name"
        aria-label="Search manufacturers"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {list.isPending && <Spinner label="Loading manufacturers" />}
      {list.isError && (
        <p className="field-error" role="alert">
          {list.error.message}
        </p>
      )}
      {star.error && (
        <p className="field-error" role="alert">
          {star.error.message}
        </p>
      )}
      {list.isSuccess && !rows.length && (
        <p className="muted">{starred && !q ? 'No starred manufacturers yet.' : 'No manufacturers found.'}</p>
      )}
      {rows.length > 0 && (
        <div className="glass p">
          <table className="tbl">
            <thead>
              <tr>
                <th>Name</th>
                <th>City</th>
                <th>Platforms</th>
                <th className="r">Listings</th>
                <th>Last seen</th>
                <th>
                  <span className="sr-only">Star</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.id}>
                  <td>
                    {m.website ? (
                      <a href={m.website} target="_blank" rel="noopener noreferrer">
                        {m.name}
                      </a>
                    ) : (
                      m.name
                    )}
                    {!m.confirmed && (
                      <>
                        {' '}
                        <Tag tone="warn">Unconfirmed</Tag>
                      </>
                    )}
                  </td>
                  <td>{m.city ?? '-'}</td>
                  <td>{m.platforms.join(', ') || '-'}</td>
                  <td className="r">{m.listing_count}</td>
                  <td className="muted">{day(m.last_seen)}</td>
                  <td>
                    <button
                      type="button"
                      className={`star${m.starred ? ' on' : ''}`}
                      aria-label={`${m.starred ? 'Unstar' : 'Star'} ${m.name}`}
                      aria-pressed={m.starred}
                      disabled={star.isPending}
                      onClick={() => star.mutate(m)}
                    >
                      <Star size={14} fill={m.starred ? 'currentColor' : 'none'} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {list.hasNextPage && (
            <Button variant="ghost" onClick={() => void list.fetchNextPage()} disabled={list.isFetchingNextPage}>
              Load more
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
