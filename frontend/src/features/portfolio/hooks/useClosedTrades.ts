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
    queryFn: getClosedTrades,
  })
}
