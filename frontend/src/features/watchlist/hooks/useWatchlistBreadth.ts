import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { getWatchlistBreadth, type BreadthResponse } from '../../../api/watchlist'
import { watchlistKeys } from './queryKeys'

/**
 * `GET /api/watchlist/breadth` — the "personal breadth" proxy across the
 * watchlist + portfolio union (docs/architecture/API.md#get-apiwatchlistbreadth,
 * docs/Analyse.md's "Personal breadth proxy" section). Typed to `ApiError`
 * (rather than TanStack Query's default `Error`) so callers can pass
 * `.error` straight into `common/ErrorState` without a cast, same as
 * useWatchlist/usePortfolioRisk.
 */
export function useWatchlistBreadth() {
  return useQuery<BreadthResponse, ApiError>({
    queryKey: watchlistKeys.breadth,
    queryFn: getWatchlistBreadth,
  })
}
