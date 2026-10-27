export function formatInr(n: number, decimals = 2): string {
  return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

export function parseIndianNumber(s: string): number | null {
  const t = s.replace(/,/g, '').trim()
  return /^\d+(\.\d+)?$/.test(t) || /^\.\d+$/.test(t) ? Number(t) : null
}
