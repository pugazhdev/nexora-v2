import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { Research, ResearchItem } from '@/api/types'
import type { StepName } from '@/components/shell/steps'

export const researchKey = (id: string) => ['research', id] as const

export const useResearch = (id: string) =>
  useQuery({ queryKey: researchKey(id), queryFn: () => api.get<Research>(`/research/${id}`) })

export const useAnalyse = () =>
  useMutation({
    mutationFn: ({ image, text }: { image?: File | null; text?: string }) => {
      const fd = new FormData()
      if (image) fd.append('image', image)
      if (text?.trim()) fd.append('text', text.trim())
      return api.post<Research>('/research', fd)
    },
  })

/** Optimistic selection toggle (or answers save); rolls back if the server refuses. */
export function usePatchItem(researchId: string) {
  const qc = useQueryClient()
  const key = researchKey(researchId)
  return useMutation({
    mutationFn: ({ itemId, ...body }: { itemId: string; selected?: boolean; answers?: ResearchItem['answers'] }) =>
      api.patch<ResearchItem>(`/research/${researchId}/items/${itemId}`, body),
    onMutate: async ({ itemId, selected }) => {
      if (selected === undefined) return { prev: undefined }
      await qc.cancelQueries({ queryKey: key })
      const prev = qc.getQueryData<Research>(key)
      if (prev)
        qc.setQueryData<Research>(key, {
          ...prev,
          items: prev.items.map((i) => (i.id === itemId ? { ...i, selected } : i)),
        })
      return { prev }
    },
    onError: (_e, _v, ctx) => ctx?.prev && qc.setQueryData(key, ctx.prev),
    onSettled: () => qc.invalidateQueries({ queryKey: key }),
  })
}

const LIVE = ['queued', 'researching']

/** Which step the research is at, from its state alone (Select to Details is the page's local choice). */
export function stepOf(r: Research): StepName {
  const runs = r.items.filter((i) => i.selected).map((i) => i.latest_run)
  if (runs.some((x) => x && LIVE.includes(x.status))) return 'Research'
  if (runs.length > 0 && runs.every((x) => x && !LIVE.includes(x.status))) return 'Results'
  return r.items.filter((i) => i.in_scope).length > 1 && !r.items.some((i) => i.latest_run) ? 'Select' : 'Details'
}

export const useStep = stepOf
