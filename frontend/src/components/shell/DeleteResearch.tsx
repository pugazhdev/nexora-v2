import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '@/api/client'

/** A row (children) with a hover/focus trash button that swaps into an inline "Delete?" confirm. */
export function DeleteResearch({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  const [confirming, setConfirming] = useState(false)
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const del = useMutation({
    mutationFn: () => api.delete(`/research/${id}`),
    onSuccess: async () => {
      if (pathname === `/research/${id}`) {
        qc.removeQueries({ queryKey: ['research', id] }) // before navigating, so it is never refetched as a 404
        navigate('/')
      }
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['research'] }),
        qc.invalidateQueries({ queryKey: ['manufacturers'] }),
      ])
    },
  })
  const cancelRef = useRef<HTMLButtonElement>(null)
  const trashRef = useRef<HTMLButtonElement>(null)
  const wasConfirming = useRef(false)
  useEffect(() => {
    if (confirming) cancelRef.current?.focus()
    else if (wasConfirming.current) trashRef.current?.focus()
    wasConfirming.current = confirming
  }, [confirming])
  const cancel = () => {
    setConfirming(false)
    del.reset()
  }
  return (
    <div className="del">
      {confirming ? (
        <div className="del-confirm">
          <span>Delete?</span>
          <button type="button" className="del-yes" disabled={del.isPending} onClick={() => del.mutate()}>
            Delete
          </button>
          <button type="button" ref={cancelRef} onClick={cancel} disabled={del.isPending}>
            Cancel
          </button>
        </div>
      ) : (
        <div className="del-row">
          {children}
          <button type="button" ref={trashRef} className="del-btn" aria-label={`Delete ${title}`} onClick={() => setConfirming(true)}>
            <Trash2 className="i" aria-hidden="true" />
          </button>
        </div>
      )}
      {del.isError && (
        <p className="del-error" role="alert">
          {del.error.message}
        </p>
      )}
    </div>
  )
}
