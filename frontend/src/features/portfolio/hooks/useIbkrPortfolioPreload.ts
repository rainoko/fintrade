import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../../api/client'
import { preloadIbkrPortfolio, type IBKRPortfolioPreloadResponse } from '../../../api/ibkr'
import { deletePosition } from '../../../api/portfolio'
import { portfolioKeys } from './queryKeys'

export interface IbkrPreloadVariables {
  /**
   * Local position ids the user chose to delete before importing
   * (backend-ibkr-portfolio-preload's requirement 4/5's exact ordering) —
   * every id here is deleted, in order, before `POST
   * /api/ibkr/portfolio-preload` is ever called.
   */
  deleteIds: string[]
}

/**
 * Deletes every position in `deleteIds` (sequentially, one `DELETE
 * /api/portfolio/positions/{id}` call at a time, reusing the same endpoint
 * `useDeletePosition` wraps — `backend-ibkr-portfolio-preload`'s own
 * `decisions` entry for why no bulk-delete endpoint exists), then calls
 * `POST /api/ibkr/portfolio-preload` — matching the backend's required
 * "deletions first, then re-checked import" ordering. Each delete uses
 * `exitReason: 'unspecified'`: none of Elder's own exit-reason taxonomy
 * (target_hit/stop_hit/reached_value_zone/...) describes "deleted to make
 * way for a fresh IBKR-sourced import" of the same ticker, so falling back
 * to the same default the backend itself uses when no reason is supplied is
 * the most honest choice available here, rather than mislabeling it as one
 * of Elder's real trading exit reasons. See this task's `decisions` entry.
 *
 * A 404 from one of the delete calls is swallowed (treated as "already
 * gone", not a failure) rather than rethrown: this whole mutation isn't
 * idempotent end to end (a DELETE call can't safely no-op the *first*
 * time), but a user retrying after an earlier attempt's *later* step failed
 * (most likely the final preload call itself, e.g. a transient 503) re-sends
 * the exact same `deleteIds` — some of which the earlier attempt may have
 * already deleted successfully. Without this, that retry would fail
 * immediately on the first already-deleted id and could never reach the
 * preload call at all. See this task's `decisions` entry.
 *
 * `onSettled` (not `onSuccess`) invalidates `portfolioKeys.all` regardless
 * of outcome, since an earlier delete step can succeed even when a *later*
 * step (another delete, or the final preload call) fails — leaving that
 * position genuinely gone server-side even though this mutation as a whole
 * reports an error. Without this, the positions table would keep showing an
 * already-deleted position as still held until some unrelated later
 * refetch. `portfolioKeys.ibkrPreview` nests under `portfolioKeys.all`
 * (queryKeys.ts), so this same invalidation also covers the preview query a
 * re-opened `IbkrPreloadDialog` reads. See this task's `decisions` entry.
 */
export function useIbkrPortfolioPreload() {
  const queryClient = useQueryClient()

  return useMutation<IBKRPortfolioPreloadResponse, ApiError, IbkrPreloadVariables>({
    mutationFn: async ({ deleteIds }) => {
      for (const id of deleteIds) {
        try {
          // Deliberately sequential (not Promise.all): the backend's own
          // ordering requirement (delete, *then* re-check conflicts) only
          // holds if every delete has actually committed before the preload
          // call below runs.
          await deletePosition(id, { exitReason: 'unspecified' })
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) {
            continue
          }
          throw error
        }
      }
      return preloadIbkrPortfolio()
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: portfolioKeys.all })
    },
  })
}
