import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import {
  addWatchlistItem,
  type WatchlistItemIn,
  type WatchlistItemOut,
} from '../../../api/watchlist'
import { watchlistKeys } from './queryKeys'

/**
 * `POST /api/watchlist` — add a ticker, or no-op if it's already watched
 * (docs/architecture/API.md#post-apiwatchlist). Invalidates the watchlist
 * query so a successful add (or a no-op re-add) is immediately reflected.
 */
export function useAddWatchlistItem() {
  const queryClient = useQueryClient()

  return useMutation<WatchlistItemOut, ApiError, WatchlistItemIn>({
    mutationFn: addWatchlistItem,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: watchlistKeys.all })
    },
  })
}
