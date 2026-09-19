import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { getStockAnalysis, type AnalysisResponse } from '../../../api/stocks'
import { stocksKeys } from './queryKeys'

/**
 * `GET /api/stocks/{ticker}/analysis` — full Triple Screen evaluation for
 * one ticker (docs/architecture/API.md#get-apistocksstickeranalysis). Typed
 * to `ApiError` (rather than TanStack Query's default `Error`) so callers
 * can pass `.error` straight into `common/ErrorState` without a cast, same
 * convention as usePortfolio/usePortfolioRisk.
 *
 * Two independent call sites share this same query key for the same ticker
 * (`StockDetailPage`'s own top-level fetch, and `PriceChart`'s own fetch of
 * `support_resistance_zones` for its zone-band overlay, frontend-support-
 * resistance-overlay) — but `StockDetailPage` only mounts `PriceChart` (via
 * `StockCharts`) once its own `analysisQuery.data` is already populated, so
 * `PriceChart`'s own `useStockAnalysis` call always mounts strictly *after*
 * the first one has already resolved, not concurrently with it (unlike
 * `useIndicatorHistory`, which `PriceChart`/`OscillatorChart` both mount
 * *at the same time* as siblings, so TanStack Query's in-flight-request
 * dedup already coalesces that pair for free). Without an explicit
 * `staleTime` here, TanStack Query's default (`0`, immediately stale)
 * treats that later mount as needing its own background refetch —
 * redundant, since the ticker and its underlying data haven't changed
 * between the two mounts. `staleTime: 60_000` (matching main.tsx's own
 * app-wide default, applied here explicitly so this guarantee holds even
 * under a bare `QueryClient` with no default overrides, e.g. this hook's
 * own tests) closes that gap: a second mount within the window reuses the
 * already-cached data instead of firing a second identical request.
 */
export function useStockAnalysis(ticker: string) {
  return useQuery<AnalysisResponse, ApiError>({
    queryKey: stocksKeys.analysis(ticker),
    queryFn: () => getStockAnalysis(ticker),
    enabled: ticker.length > 0,
    staleTime: 60_000,
  })
}
