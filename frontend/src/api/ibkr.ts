// Typed endpoint functions for GET /api/ibkr/status and POST
// /api/ibkr/breadth/snapshot (docs/architecture/API.md). Response shapes
// come straight from the generated types.ts.

import { request } from './client'
import type { components } from './types'

export type IBKRStatusResponse = components['schemas']['IBKRStatusResponse']
export type IBKRBreadthSnapshotRequest = components['schemas']['IBKRBreadthSnapshotRequest']
export type IBKRBreadthSnapshotResponse = components['schemas']['IBKRBreadthSnapshotResponse']

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

/**
 * `POST /api/ibkr/breadth/snapshot` — records (or fetches, on a same-day
 * cache hit) one `series_key`'s IBKR-scanner-based breadth count for today,
 * plus its 5-day/20-day rolling sums (docs/architecture/API.md,
 * `frontend-market-breadth-widget`). Same "never a non-2xx response for a
 * gateway-availability state" contract as `getIbkrStatus` above — a `429`
 * (rate-limited, with `ApiError.retryAfterSeconds` set) or `503` (a
 * transient scan-call failure) are the only failure modes this can reject
 * with, both only reachable on a same-day cache miss.
 */
export function recordIbkrBreadthSnapshot(
  body: IBKRBreadthSnapshotRequest,
): Promise<IBKRBreadthSnapshotResponse> {
  return request<IBKRBreadthSnapshotResponse>('/api/ibkr/breadth/snapshot', {
    method: 'POST',
    body,
  })
}
