// Typed endpoint functions for the /api/portfolio/* routes (docs/architecture/API.md).
// Response/request shapes come straight from the generated types.ts.

import { request } from './client'
import type { components } from './types'

export type PortfolioResponse = components['schemas']['PortfolioResponse']
export type RiskResponse = components['schemas']['RiskResponse']
export type RiskPosition = components['schemas']['RiskPosition']
export type PositionIn = components['schemas']['PositionIn']
export type PositionOut = components['schemas']['PositionOut']
export type ClosedTradeOut = components['schemas']['ClosedTradeOut']
export type ClosedTradesResponse = components['schemas']['ClosedTradesResponse']
export type FollowUpReviewIn = components['schemas']['FollowUpReviewIn']
export type TradeApgarIn = components['schemas']['TradeApgarIn']
export type TradeApgarOut = components['schemas']['TradeApgarOut']
export type TradeApgarQuestionOut = components['schemas']['TradeApgarQuestionOut']

/** `GET /api/portfolio` — current positions plus account equity. */
export function getPortfolio(): Promise<PortfolioResponse> {
  return request<PortfolioResponse>('/api/portfolio')
}

/** `GET /api/portfolio/risk` — portfolio-level 2%/6% rule evaluation (Analyse.md §7). */
export function getPortfolioRisk(): Promise<RiskResponse> {
  return request<RiskResponse>('/api/portfolio/risk')
}

/**
 * `POST /api/portfolio/positions` — add a position. Adding a ticker that's
 * already held merges into the existing position (quantity-weighted average
 * cost basis) rather than creating a duplicate row — see API.md.
 */
export function addPosition(payload: PositionIn): Promise<PositionOut> {
  return request<PositionOut>('/api/portfolio/positions', {
    method: 'POST',
    body: payload,
  })
}

/** `DELETE /api/portfolio/positions/{id}` — removes a position entirely. */
export function deletePosition(id: string): Promise<void> {
  return request<void>(`/api/portfolio/positions/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
}

/**
 * `GET /api/portfolio/closed-trades` — trade history (the `closed_trades`
 * table), most recently exited first, each row annotated with its
 * buy/sell/trade "A-trade" grades (Elder ch. 55, docs/Analyse.md §7). Grade
 * fields are `null` whenever they can't currently be computed — never a
 * request-level error (see API.md).
 *
 * Pass `{ dueForFollowUp: true }` to narrow the response to trades due for
 * Elder's mandatory two-months-later follow-up review right now (ch. 59
 * Trade Journal Section E) — `follow_up_reviewed_at` still null and
 * `exit_date` between 8 and 10 weeks ago inclusive (API.md's
 * `due_for_follow_up` query parameter). Omitted/false returns every closed
 * trade, unfiltered — the original behavior.
 */
export function getClosedTrades(params?: {
  dueForFollowUp?: boolean
}): Promise<ClosedTradesResponse> {
  const query = params?.dueForFollowUp ? '?due_for_follow_up=true' : ''
  return request<ClosedTradesResponse>(`/api/portfolio/closed-trades${query}`)
}

/**
 * `POST /api/portfolio/closed-trades/{trade_id}/follow-up-review` — records
 * Elder's mandatory two-months-later follow-up review (ch. 59 Trade Journal
 * Section E) for one closed trade: `follow_up_notes` plus `follow_up_reviewed_at`
 * set to now. Calling this again for the same `trade_id` overwrites both
 * fields with the new call's values rather than appending or rejecting the
 * second call (API.md). Returns the full updated `ClosedTradeOut`, including
 * a freshly recomputed grade.
 */
export function recordFollowUpReview(
  tradeId: string,
  payload: FollowUpReviewIn,
): Promise<ClosedTradeOut> {
  return request<ClosedTradeOut>(
    `/api/portfolio/closed-trades/${encodeURIComponent(tradeId)}/follow-up-review`,
    { method: 'POST', body: payload },
  )
}

/**
 * `POST /api/portfolio/trade-apgar` — scores Elder ch. 58's pre-trade "Trade
 * Apgar" go/no-go check for `payload.ticker` (Analyse.md §7, `docs/ideas.md`
 * ch. 58). Stateless: nothing is persisted, this just scores whatever ticker
 * and manual answers (`false_breakout_status`/`perfection`) the request
 * supplies at the time of the call, and can be called again with different
 * manual answers to re-score the same ticker.
 */
export function scoreTradeApgar(payload: TradeApgarIn): Promise<TradeApgarOut> {
  return request<TradeApgarOut>('/api/portfolio/trade-apgar', {
    method: 'POST',
    body: payload,
  })
}
