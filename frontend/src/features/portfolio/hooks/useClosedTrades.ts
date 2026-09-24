import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { getClosedTrades, type ClosedTradesResponse } from '../../../api/portfolio'
import { portfolioKeys } from './queryKeys'

/**
 * `GET /api/portfolio/closed-trades` — trade history (the `closed_trades`
 * table) with each row's buy/sell/trade "A-trade" grades
 * (docs/architecture/API.md#get-apiportfolioclosed-trades, docs/Analyse.md
 * §7). Typed to `ApiError` (rather than TanStack Query's default `Error`) so
 * callers can pass `.error` straight into `common/ErrorState` without a
 * cast, same as usePortfolio/usePortfolioRisk.
 */
export function useClosedTrades() {
  return useQuery<ClosedTradesResponse, ApiError>({
    queryKey: portfolioKeys.closedTrades,
    queryFn: () => getClosedTrades(),
  })
}

/**
 * The same `GET /api/portfolio/closed-trades` resource, narrowed to
 * `?due_for_follow_up=true` — trades due right now for Elder's mandatory
 * two-months-later follow-up review (ch. 59 Trade Journal Section E,
 * docs/architecture/API.md). A separate query key
 * (`portfolioKeys.dueForFollowUpTrades`) from `useClosedTrades` above since
 * it's a genuinely different filtered response, not just a client-side
 * re-slice of the same data.
 */
export function useDueForFollowUpTrades() {
  return useQuery<ClosedTradesResponse, ApiError>({
    queryKey: portfolioKeys.dueForFollowUpTrades,
    queryFn: () => getClosedTrades({ dueForFollowUp: true }),
  })
}
