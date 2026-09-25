// Typed endpoint functions for /api/settings/trading-mode
// (docs/architecture/API.md#get-apisettingstrading-mode--put-apisettingstrading-mode).
// Response/request shapes come straight from the generated types.ts.

import { request } from './client'
import type { components } from './types'

export type TradingModeIn = components['schemas']['TradingModeIn']
export type TradingModeOut = components['schemas']['TradingModeOut']
export type TimeframeTripleIn = components['schemas']['TimeframeTripleIn']
export type TimeframeTripleOut = components['schemas']['TimeframeTripleOut']

/**
 * `GET /api/settings/trading-mode` — the currently-active global trading
 * mode ('swing' or 'day_trader') and, if one has ever been configured, the
 * persisted day-trader timeframe triple. Never 404s — `mode: 'swing'` with a
 * null triple is the normal response for a database that has never had this
 * setting written.
 */
export function getTradingMode(): Promise<TradingModeOut> {
  return request<TradingModeOut>('/api/settings/trading-mode')
}

/**
 * `PUT /api/settings/trading-mode` — switches the global trading mode,
 * persisting the supplied day-trader timeframe triple when `mode` is
 * 'day_trader'. Raises a 422 (see API.md) if `mode` is 'day_trader' with no
 * `day_trader_timeframe_triple` supplied, or if the triple's three legs
 * aren't in strictly-decreasing `long_term > intermediate > short_term`
 * order — both are left for the backend to enforce rather than duplicated
 * here (see the `frontend-day-trader-timeframe-mode-settings` task's
 * `decisions` entry).
 */
export function updateTradingMode(payload: TradingModeIn): Promise<TradingModeOut> {
  return request<TradingModeOut>('/api/settings/trading-mode', {
    method: 'PUT',
    body: payload,
  })
}
