export class ApiError extends Error {
  code: string
  details: unknown
  status: number
  constructor(code: string, message: string, details: unknown = {}, status = 0) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.details = details
    this.status = status
  }
}

const BASE = '/api'

async function request<T>(method: string, path: string, body?: FormData | object): Promise<T> {
  const init: RequestInit = { method }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { 'Content-Type': 'application/json' }
  }
  let res: Response
  try {
    res = await fetch(BASE + path, init)
  } catch {
    throw new ApiError('network', 'Could not reach the server. Check your connection and try again.')
  }
  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    // non-JSON body: handled below
  }
  if (!res.ok) {
    const e = (data as { error?: { code?: string; message?: string; details?: unknown } } | null)?.error
    throw new ApiError(
      e?.code ?? 'http_error',
      e?.message ?? `Request failed (${res.status})`,
      e?.details ?? {},
      res.status,
    )
  }
  return data as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: FormData | object) => request<T>('POST', path, body),
  patch: <T>(path: string, body: object) => request<T>('PATCH', path, body),
  delete: (path: string) => request<null>('DELETE', path),
}

/** Money fields arrive as Decimal strings; parse only for display and calculator maths. */
export const toNumber = (v: string | number | null | undefined): number => (v == null ? NaN : Number(v))
