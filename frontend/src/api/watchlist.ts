// Typed endpoint functions for the /api/watchlist* routes (docs/architecture/API.md).
// Response/request shapes come straight from the generated types.ts.

import { request } from './client'
import type { components } from './types'

export type WatchlistResponse = components['schemas']['WatchlistResponse']
export type WatchlistItemIn = components['schemas']['WatchlistItemIn']
export type WatchlistItemOut = components['schemas']['WatchlistItemOut']
export type BreadthResponse = components['schemas']['BreadthResponse']

/**
 * `GET /api/watchlist` — every watched ticker, annotated with its current
 * BUY/SELL/HOLD signal via the same Triple Screen engine `/api/stocks/{ticker}/analysis`
 * uses. `signal`/`confidence`/`confidence_band` are `null` together on an
 * entry whose signal couldn't be computed right now (API.md).
 */
export function getWatchlist(): Promise<WatchlistResponse> {
  return request<WatchlistResponse>('/api/watchlist')
}

/**
 * `POST /api/watchlist` — add a ticker. Adding a ticker already on the
 * watchlist is an idempotent no-op (the existing entry, original `added_at`
 * kept, is returned unchanged) rather than creating a duplicate or erroring.
 */
export function addWatchlistItem(payload: WatchlistItemIn): Promise<WatchlistItemOut> {
  return request<WatchlistItemOut>('/api/watchlist', {
    method: 'POST',
    body: payload,
  })
}

/** `DELETE /api/watchlist/{ticker}` — removes a ticker from the watchlist. */
export function removeWatchlistItem(ticker: string): Promise<void> {
  return request<void>(`/api/watchlist/${encodeURIComponent(ticker)}`, {
    method: 'DELETE',
  })
}

/**
 * `GET /api/watchlist/breadth` — "personal breadth": counts/percentages of
 * BULLISH/BEARISH/NEUTRAL Screen 1 (Tide) trend across the union of the
 * watchlist and portfolio tickers (deduplicated). An explicit, honestly
 * framed proxy for true market breadth, not the real thing — see
 * docs/Analyse.md's "Personal breadth proxy" section (API.md).
 */
export function getWatchlistBreadth(): Promise<BreadthResponse> {
  return request<BreadthResponse>('/api/watchlist/breadth')
}
