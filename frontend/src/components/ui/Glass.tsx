import clsx from 'clsx'
import type { HTMLAttributes } from 'react'

export function Glass({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div className={clsx('glass', className)} {...p} />
}
