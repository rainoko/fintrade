// Typed endpoint functions for the /api/portfolio/* routes (docs/architecture/API.md).
// Response/request shapes come straight from the generated types.ts.

import { request } from './client'
import type { components } from './types'

export type PortfolioResponse = components['schemas']['PortfolioResponse']
export type RiskResponse = components['schemas']['RiskResponse']
export type RiskPosition = components['schemas']['RiskPosition']
export type PositionIn = components['schemas']['PositionIn']
export type PositionOut = components['schemas']['PositionOut']
export type ExitReason = components['schemas']['ExitReason']
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

export interface DeletePositionParams {
  /**
   * Why this position is being closed (Elder's own exit-reason taxonomy,
   * `ExitReason`) — omitted entirely (rather than sent as `'unspecified'`)
   * when the caller doesn't have one, since the backend's own default is
   * already `'unspecified'` and there's no behavioral difference either way;
   * omitting it just keeps the query string free of a redundant param.
   */
  exitReason?: ExitReason
  /**
   * Optional manual exit-price/date override for backfilling a trade that
   * already happened in the past (backend-close-position-manual-exit) —
   * should be supplied together with `exitDate` or not at all, exactly like
   * the backend's own `exit_price`/`exit_date` query params, but this
   * function forwards each independently rather than silently dropping a
   * mismatched single one -- ClosePositionDialog's own client-side
   * validation is what actually enforces "both or neither" before this is
   * ever called; a caller that gets it wrong anyway should see the
   * backend's own 422 for it, not a request that silently looks like the
   * no-override default instead. Omitted entirely when not supplied,
   * keeping the original default (today's live market close) unchanged.
   */
  exitPrice?: number
  exitDate?: string
}

/**
 * `DELETE /api/portfolio/positions/{id}` — removes a position entirely,
 * recording it as a closed trade priced either at today's live market close
 * (the default) or at the caller-supplied `exitPrice`/`exitDate` override.
 */
export function deletePosition(id: string, params: DeletePositionParams = {}): Promise<void> {
  const query = new URLSearchParams()
  if (params.exitReason) {
    query.set('exit_reason', params.exitReason)
  }
  if (params.exitPrice !== undefined) {
    query.set('exit_price', String(params.exitPrice))
  }
  if (params.exitDate !== undefined) {
    query.set('exit_date', params.exitDate)
  }
  const queryString = query.toString()
  return request<void>(
    `/api/portfolio/positions/${encodeURIComponent(id)}${queryString ? `?${queryString}` : ''}`,
    { method: 'DELETE' },
  )
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
