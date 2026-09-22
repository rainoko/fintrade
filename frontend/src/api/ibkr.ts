// Typed endpoint function for GET /api/ibkr/status (docs/architecture/API.md).
// Response shape comes straight from the generated types.ts.

import { request } from './client'
import type { components } from './types'

export type IBKRStatusResponse = components['schemas']['IBKRStatusResponse']

/**
 * `GET /api/ibkr/status` — whether the optional IBKR Client Portal Gateway
 * integration is usable right now. Never returns a non-2xx response for any
 * gateway state (`disabled`/`available`/`gateway_unreachable`/
 * `not_authenticated` are all plain `200` bodies, per API.md) — the only way
 * this can reject is a genuine transport-level failure (this app's own
 * backend being unreachable), surfaced as `api/client.ts`'s `ApiError` with
 * `status: 0`.
 */
export function getIbkrStatus(): Promise<IBKRStatusResponse> {
  return request<IBKRStatusResponse>('/api/ibkr/status')
}
