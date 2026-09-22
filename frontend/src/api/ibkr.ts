// Typed endpoint functions for the market-scanner slice of /api/ibkr*
// (docs/architecture/API.md). GET /api/ibkr/status itself has no frontend
// consumer yet (that's the separate, still-planned
// frontend-ibkr-status-indicator task) -- only the two scanner routes are
// wired here.

import { request } from './client'
import type { components } from './types'

export type IBKRScannerParamsResponse = components['schemas']['IBKRScannerParamsResponse']
export type IBKRScannerRunRequest = components['schemas']['IBKRScannerRunRequest']
export type IBKRScannerRunResponse = components['schemas']['IBKRScannerRunResponse']
export type IBKRScannerResultOut = components['schemas']['IBKRScannerResultOut']

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
