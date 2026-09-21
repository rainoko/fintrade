// Thin fetch wrapper shared by every api/<domain>.ts module: base URL
// resolution, JSON parsing, and mapping every documented error case
// (docs/architecture/API.md's "Error Cases to Cover in Tests" — 404/422/503)
// to a typed ApiError with a `status` and human-readable `detail`, so
// ErrorState (components/common/ErrorState) can render a distinct message
// per case rather than one generic "something went wrong" (see
// docs/architecture/Frontend.md §7).

import type { components } from './types'

type ErrorDetail = components['schemas']['ErrorDetail']
type HTTPValidationError = components['schemas']['HTTPValidationError']

/**
 * Typed error thrown by every api/<domain>.ts function for a non-2xx
 * response (including a network-level failure, `status: 0`). `detail` is
 * always a plain, displayable string — the two distinct 422 body shapes the
 * backend can send (a single ErrorDetail vs. FastAPI's per-field
 * HTTPValidationError list, see API.md) are normalized here so callers never
 * need to know which one they got.
 *
 * `retryAfterSeconds` surfaces the `Retry-After` header a 429 response (e.g.
 * POST /api/ibkr/scanner/run, POST /api/ibkr/breadth/snapshot) carries —
 * `null` for every other status, or if the header is present but not a
 * plain integer-seconds value (a HTTP-date `Retry-After` is legal per RFC
 * 9110 §10.2.3, but neither backend route in this app ever sends one).
 * `Response.headers.get()` always returns a `string | null` — never the
 * generated OpenAPI `number` type response bodies get — so this parses it
 * explicitly rather than casting.
 */
export class ApiError extends Error {
  readonly status: number
  readonly detail: string
  readonly retryAfterSeconds: number | null

  constructor(status: number, detail: string, retryAfterSeconds: number | null = null) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.retryAfterSeconds = retryAfterSeconds
  }
}

function parseRetryAfterSeconds(response: Response): number | null {
  const header = response.headers.get('Retry-After')
  if (header === null) {
    return null
  }
  // Only the integer-seconds form is parsed (see class doc above) — reject
  // anything Number() would otherwise coerce oddly (e.g. '', whitespace), via
  // a digits-only regex rather than a direct cast.
  const trimmed = header.trim()
  return /^\d+$/.test(trimmed) ? Number(trimmed) : null
}

// Decision (frontend-api-client task): base URL is read from
// VITE_API_BASE_URL, defaulting to '' (same-origin — every endpoint path
// already includes the '/api' prefix per API.md, so a same-origin deploy or
// a dev-server proxy both work with no further config). Rejected
// alternative: hardcoding 'http://localhost:8000' as the default, which
// would silently break in any non-local deployment; an explicit env var
// with an empty-string default fails loudly (relative fetch to the frontend
// origin, a 404) instead.
function getBaseUrl(): string {
  return import.meta.env.VITE_API_BASE_URL ?? ''
}

function extractDetail(body: unknown, status: number): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as ErrorDetail | HTTPValidationError).detail
    if (typeof detail === 'string') {
      return detail
    }
    if (Array.isArray(detail)) {
      const messages = detail.map((item) => item.msg).filter(Boolean)
      if (messages.length > 0) {
        return messages.join('; ')
      }
    }
  }
  return `Request failed with status ${status}`
}

async function safeParseJson(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) {
    return undefined
  }
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'DELETE'
  body?: unknown
}

/**
 * Issues one API request and either resolves with the parsed JSON body (typed
 * as `T` by the caller) or rejects with an `ApiError`. A `204 No Content`
 * response (DELETE endpoints) resolves with `undefined`.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body } = options
  const url = `${getBaseUrl()}${path}`

  let response: Response
  try {
    response = await fetch(url, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    // A network-level failure (backend unreachable, DNS, CORS) never
    // surfaces as a thrown TypeError to callers — it's normalized into the
    // same ApiError shape as every other failure, with status 0 marking it
    // as "not an HTTP response at all" (distinct from a real 503).
    throw new ApiError(0, 'Unable to reach the API. Check your connection and try again.')
  }

  if (response.status === 204) {
    return undefined as T
  }

  const parsed = await safeParseJson(response)

  if (!response.ok) {
    throw new ApiError(
      response.status,
      extractDetail(parsed, response.status),
      parseRetryAfterSeconds(response),
    )
  }

  return parsed as T
}
