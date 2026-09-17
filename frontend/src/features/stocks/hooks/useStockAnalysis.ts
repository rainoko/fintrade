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
 */
export function useStockAnalysis(ticker: string) {
  return useQuery<AnalysisResponse, ApiError>({
    queryKey: stocksKeys.analysis(ticker),
    queryFn: () => getStockAnalysis(ticker),
    enabled: ticker.length > 0,
  })
}
