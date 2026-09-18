import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { removeWatchlistItem } from '../../../api/watchlist'
import { watchlistKeys } from './queryKeys'

/**
 * `DELETE /api/watchlist/{ticker}` — removes a ticker entirely
 * (docs/architecture/API.md#delete-apiwatchlistticker). Invalidates the
 * watchlist query so the removed ticker disappears immediately rather than
 * lingering until an unrelated refetch.
 */
export function useRemoveWatchlistItem() {
  const queryClient = useQueryClient()

  return useMutation<void, ApiError, string>({
    mutationFn: (ticker: string) => removeWatchlistItem(ticker),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: watchlistKeys.all })
    },
  })
}
