import clsx from 'clsx'
import type { HTMLAttributes } from 'react'

export function Tag({
  tone = 'neutral',
  className,
  ...p
}: HTMLAttributes<HTMLSpanElement> & { tone?: 'neutral' | 'ok' | 'warn' | 'bad' }) {
  return <span className={clsx('tag', `tag-${tone}`, className)} {...p} />
}
