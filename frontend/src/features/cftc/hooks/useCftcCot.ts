import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { getCftcCot, type CFTCCOTResponse } from '../../../api/cftc'
import { cftcKeys } from './queryKeys'

/**
 * `GET /api/cftc/cot` — CFTC Commitments of Traders positioning for this
 * app's fixed 5 futures markets (docs/architecture/API.md,
 * docs/ideas.md's ch. 37 entry). Typed to `ApiError` (rather than TanStack
 * Query's default `Error`) so callers can pass `.error` straight into
 * `common/ErrorState` without a cast, same as `useWatchlistBreadth`/
 * `usePortfolioRisk`.
 *
 * No `staleTime` override: the backend's own cache only refreshes weekly
 * (matching the CFTC's publication cadence), so this app's default
 * query-level staleness (`main.tsx`) is already far shorter than the data
 * itself ever actually changes — a shared concern across every CFTC-backed
 * widget, not something to special-case per call site.
 */
export function useCftcCot() {
  return useQuery<CFTCCOTResponse, ApiError>({
    queryKey: cftcKeys.cot,
    queryFn: getCftcCot,
  })
}
