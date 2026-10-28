import type { RetailResult } from '@/api/types'
import { Glass } from '@/components/ui/Glass'
import { Spinner } from '@/components/ui/Spinner'
import { formatInr } from '@/lib/format'

const pack = (n: number) => (n === 1 ? 'Single unit' : `Pack of ${n.toLocaleString('en-IN')}`)

/** Retail prices for reference only; never part of the factory range or the calculator. */
export function RetailCard({ retail, running }: { retail: RetailResult | null | undefined; running: boolean }) {
  const rows = [...(retail?.rows ?? [])].sort((a, b) => Number(a.unit_price) - Number(b.unit_price)).slice(0, 5)
  return (
    <Glass className="rc retail">
      <div className="rc-head">
        <h2>Retail price</h2>
      </div>
      {rows.length > 0 ? (
        <>
          <table className="split-table">
            <thead>
              <tr>
                <th>Retailer</th>
                <th>Product</th>
                <th>Pack</th>
                <th className="r">Per unit</th>
                <th className="r">Pack price</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.url}>
                  <td>{r.retailer}</td>
                  <td>
                    <a href={r.url} target="_blank" rel="noopener noreferrer">
                      {r.title}
                    </a>
                  </td>
                  <td>{pack(r.pack_size)}</td>
                  <td className="r">{formatInr(Number(r.unit_price))}</td>
                  <td className="r">{formatInr(Number(r.pack_price))}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">Retail prices for reference; they include retailer margin and GST.</p>
        </>
      ) : running ? (
        <p className="muted">
          <Spinner label="Finding retail prices" /> Finding retail prices...
        </p>
      ) : (
        <p className="muted">No retail price found</p>
      )}
    </Glass>
  )
}
