import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { getIbkrPortfolioPreview, type IBKRPortfolioPreviewResponse } from '../../../api/ibkr'
import { portfolioKeys } from './queryKeys'

/**
 * `GET /api/ibkr/portfolio-preview` (docs/architecture/API.md) —
 * `IbkrPreloadDialog`'s own data source. Fetched on demand only while the
 * dialog is open (`enabled: open`), not eagerly whenever the Portfolio page
 * loads, since this makes a real IBKR gateway round trip that's only
 * relevant once the user has actually asked to preload.
 *
 * `staleTime: 0` overrides this app's global 60s default (`main.tsx`):
 * re-opening the dialog after an earlier close (add/delete a position
 * elsewhere, or a previous preload attempt) must always show a fresh
 * conflict read against the local `positions` table's CURRENT state, not a
 * cached one from before — this is exactly the question the dialog exists
 * to answer, and a stale answer here would misinform which conflicts the
 * user is choosing to resolve. See the frontend-ibkr-portfolio-preload
 * task's `decisions` entry.
 */
export function useIbkrPortfolioPreview(open: boolean) {
  return useQuery<IBKRPortfolioPreviewResponse, ApiError>({
    queryKey: portfolioKeys.ibkrPreview,
    queryFn: getIbkrPortfolioPreview,
    enabled: open,
    staleTime: 0,
  })
}
