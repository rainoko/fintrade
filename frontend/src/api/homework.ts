// Typed endpoint functions for the /api/daily-homework* routes
// (docs/architecture/API.md). Response/request shapes come straight from
// the generated types.ts.

import { request } from './client'
import type { components } from './types'

export type DailyHomeworkIn = components['schemas']['DailyHomeworkIn']
export type DailyHomeworkOut = components['schemas']['DailyHomeworkOut']
export type DailyHomeworkTodayResponse = components['schemas']['DailyHomeworkTodayResponse']
export type YesterdayTradingSuggestionOut = components['schemas']['YesterdayTradingSuggestionOut']
export type HomeworkBand = DailyHomeworkOut['band']

/**
 * `GET /api/daily-homework/today` — today's (server UTC date) recorded
 * self-test entry, or a null `entry` if it hasn't been recorded yet. Never
 * 404s — "not done yet today" is the normal state for most of the day.
 */
export function getDailyHomeworkToday(): Promise<DailyHomeworkTodayResponse> {
  return request<DailyHomeworkTodayResponse>('/api/daily-homework/today')
}

/**
 * `POST /api/daily-homework` — records (or overwrites) a calendar day's
 * five 0/1/2 self-test scores. Submitting for a day that already has an
 * entry overwrites it rather than rejecting or duplicating — see API.md.
 */
export function recordDailyHomework(payload: DailyHomeworkIn): Promise<DailyHomeworkOut> {
  return request<DailyHomeworkOut>('/api/daily-homework', {
    method: 'POST',
    body: payload,
  })
}

/**
 * `GET /api/daily-homework/yesterday-trading-suggestion` — a suggested
 * (never authoritative) value for the "how did I trade yesterday?" question,
 * derived from yesterday's closed-trade realized P&L. `net_realized_pnl`/
 * `suggested_score` are both null when nothing closed yesterday.
 */
export function getYesterdayTradingSuggestion(): Promise<YesterdayTradingSuggestionOut> {
  return request<YesterdayTradingSuggestionOut>('/api/daily-homework/yesterday-trading-suggestion')
}
