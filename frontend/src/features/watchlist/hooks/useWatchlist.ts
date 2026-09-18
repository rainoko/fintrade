import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { getWatchlist, type WatchlistResponse } from '../../../api/watchlist'
import { watchlistKeys } from './queryKeys'

/**
 * `GET /api/watchlist` — every watched ticker plus its current signal
 * (docs/architecture/API.md#get-apiwatchlist). Typed to `ApiError` (rather
 * than TanStack Query's default `Error`) so callers can pass `.error`
 * straight into `common/ErrorState` without a cast.
 */
export function useWatchlist() {
  return useQuery<WatchlistResponse, ApiError>({
    queryKey: watchlistKeys.all,
    queryFn: getWatchlist,
  })
}
