import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import {
  getStockHistory,
  type HistoryInterval,
  type HistoryResponse,
} from '../../../api/stocks'
import { stocksKeys } from './queryKeys'

export interface UseStockHistoryParams {
  /** '<N>d' | '<N>w' | '<N>m' | '<N>y' | 'max' (see API.md). */
  range: string
  interval: HistoryInterval
}

/**
 * `GET /api/stocks/{ticker}/history` — raw OHLCV bars for `PriceChart.tsx`
 * (docs/architecture/API.md#get-apistocksstickerhistory). `range`/`interval`
 * are part of the query key (see queryKeys.ts) rather than fixed params, so
 * changing either one addresses a fresh cache entry and triggers a genuine
 * refetch instead of TanStack Query serving a previous range/interval's
 * cached bars while the new request is in flight. Typed to `ApiError` (not
 * TanStack Query's default `Error`) so callers can pass `.error` straight
 * into `common/ErrorState`, same convention as useStockAnalysis.
 */
export function useStockHistory(
  ticker: string,
  { range, interval }: UseStockHistoryParams,
) {
  return useQuery<HistoryResponse, ApiError>({
    queryKey: stocksKeys.history(ticker, range, interval),
    queryFn: () => getStockHistory(ticker, { range, interval }),
    enabled: ticker.length > 0,
  })
}
