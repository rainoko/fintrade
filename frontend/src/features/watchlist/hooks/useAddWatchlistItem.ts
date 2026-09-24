import { useMutation, useQueryClient, type MutationKey } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import {
  addWatchlistItem,
  type WatchlistItemIn,
  type WatchlistItemOut,
} from '../../../api/watchlist'
import { watchlistKeys } from './queryKeys'

export interface UseAddWatchlistItemOptions {
  /**
   * Overrides the mutation-cache key this call is registered under. Defaults
   * to `watchlistKeys.add`, the key WatchlistTable's own `useMutationState`
   * reads to render its pending-add skeleton row (see that component's doc
   * comment). A caller *outside* the watchlist feature — e.g. the Scanner
   * page's `ScannerAddToWatchlistButton`, which reuses this hook for the
   * exact same idempotent-add/invalidate behavior rather than duplicating it
   * (this task's own cross-feature-hook-reuse `decisions` entry) — must pass
   * a *different* key here. `useMutation`'s cache is a single, app-wide,
   * per-`QueryClient` store keyed only by `mutationKey`, not scoped by which
   * component/page called `mutate()`; leaving every caller on the same
   * default key means WatchlistTable's filter can't tell "an add dispatched
   * from the Watchlist page's own AddTickerForm" apart from "an add
   * dispatched from a completely different page" and would render a phantom
   * skeleton row for a ticker the Watchlist page's own user never touched
   * (round-4 regression, PR #243 frontend-market-scanner-page).
   */
  mutationKey?: MutationKey
}

/**
 * `POST /api/watchlist` — add a ticker, or no-op if it's already watched
 * (docs/architecture/API.md#post-apiwatchlist). Invalidates the watchlist
 * query so a successful add (or a no-op re-add) is immediately reflected.
 *
 * Unlike useRemoveWatchlistItem's fire-and-forget invalidate, this
 * `onSuccess` *returns* (awaits) `invalidateQueries` rather than firing it
 * off with `void` — TanStack Query keeps a mutation's `status` at
 * `'pending'` until its `onSuccess` option resolves, so awaiting here keeps
 * `isPending` true for the *entire* add flow, not just the fast POST. The
 * perceptible delay a user actually experiences isn't the POST (which just
 * writes one row) — it's this invalidated GET refetch, which recomputes a
 * signal for every watched ticker including the brand-new one
 * (frontend-watchlist-add-skeleton). Extending `isPending` this way is what
 * lets AddTickerForm's own submit button stay disabled/spinning for that
 * whole window instead of appearing to finish early, and is what lets
 * WatchlistTable observe "an add is still in flight" for the same window via
 * `useMutationState({ filters: { mutationKey: watchlistKeys.add, status:
 * 'pending' } })` (see that component and this task's `decisions`) without
 * needing this mutation's object passed to it directly.
 */
export function useAddWatchlistItem({ mutationKey = watchlistKeys.add }: UseAddWatchlistItemOptions = {}) {
  const queryClient = useQueryClient()

  return useMutation<WatchlistItemOut, ApiError, WatchlistItemIn>({
    mutationKey,
    mutationFn: addWatchlistItem,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: watchlistKeys.all }),
  })
}
