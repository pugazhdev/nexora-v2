import type { ResearchItem, Research, ItemRun } from '@/api/types'

export const item = (o: Partial<ResearchItem> = {}): ResearchItem => ({
  id: 'i1',
  position: 0,
  name: 'Surgical face mask',
  category: 'consumable',
  in_scope: true,
  scope_reason: null,
  selected: true,
  known_attributes: [],
  questions: [],
  answers: {},
  answer_errors: {},
  splittable: false,
  parts: [],
  image_region_hint: '3-ply, ear loop',
  latest_run: null,
  ...o,
})

export const run = (status: ItemRun['status']) => ({ id: 'r', status }) as ItemRun

export const research = (items: ResearchItem[], o: Partial<Research> = {}): Research => ({
  id: 'r1',
  title: 't',
  created_at: '2026-10-26T00:00:00Z',
  image_path: null,
  status: 'draft',
  message: null,
  items,
  ...o,
})
