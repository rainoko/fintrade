// Typed endpoint functions for /api/ibkr* (docs/architecture/API.md): the
// gateway status/breadth-snapshot slice (GET /api/ibkr/status, POST
// /api/ibkr/breadth/snapshot) and the market-scanner slice (GET
// /api/ibkr/scanner/params, POST /api/ibkr/scanner/run). Response shapes come
// straight from the generated types.ts.

import { request } from './client'
import type { components } from './types'

export type IBKRStatusResponse = components['schemas']['IBKRStatusResponse']
export type IBKRBreadthSnapshotRequest = components['schemas']['IBKRBreadthSnapshotRequest']
export type IBKRBreadthSnapshotResponse = components['schemas']['IBKRBreadthSnapshotResponse']
export type IBKRScannerParamsResponse = components['schemas']['IBKRScannerParamsResponse']
export type IBKRScannerRunRequest = components['schemas']['IBKRScannerRunRequest']
export type IBKRScannerRunResponse = components['schemas']['IBKRScannerRunResponse']
export type IBKRScannerResultOut = components['schemas']['IBKRScannerResultOut']

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

/**
 * `GET /api/ibkr/scanner/params` — IBKR's own predefined scan categories, or
 * why the scanner is currently unavailable. Never rejects for a `state` of
 * `disabled`/`gateway_unreachable`/`not_authenticated` — those are normal
 * `200` responses (API.md) — only a genuine transport/5xx failure rejects
 * with an `ApiError`.
 */
export function getIbkrScannerParams(): Promise<IBKRScannerParamsResponse> {
  return request<IBKRScannerParamsResponse>('/api/ibkr/scanner/params')
}

/**
 * `POST /api/ibkr/scanner/run` — runs one scan via `scan_config`. Same
 * never-rejects-for-unavailability convention as
 * `GET /api/ibkr/scanner/params` above; a `429` (rate-limited, more than one
 * scan/second) or `503` (transient scan-call failure) does reject with an
 * `ApiError` — see `ApiError.retryAfterSeconds` for the `429` case's
 * `Retry-After` header.
 */
export function runIbkrScanner(payload: IBKRScannerRunRequest): Promise<IBKRScannerRunResponse> {
  return request<IBKRScannerRunResponse>('/api/ibkr/scanner/run', {
    method: 'POST',
    body: payload,
  })
}
