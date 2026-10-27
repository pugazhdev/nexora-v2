import clsx from 'clsx'
import type { ButtonHTMLAttributes } from 'react'

export function Button({
  variant = 'primary',
  className,
  ...p
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'ghost' }) {
  return <button className={clsx('btn', `btn-${variant}`, className)} {...p} />
}
