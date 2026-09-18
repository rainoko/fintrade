import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { getIndicatorHistory, type IndicatorHistoryResponse } from '../../../api/stocks'
import { stocksKeys } from './queryKeys'

export interface UseIndicatorHistoryParams {
  /** '<N>d' | '<N>w' | '<N>m' | '<N>y' | 'max' (see API.md) — same grammar as useStockHistory's `range`. */
  range: string
}

export interface UseIndicatorHistoryOptions {
  /**
   * Lets a caller gate the request on something beyond "ticker is present"
   * (e.g. PriceChart/OscillatorChart only want this fetched while the
   * daily interval is selected — indicators are daily-cadence only, see
   * PriceChart.tsx's decisions entry). Defaults to `true` so a caller with
   * no such constraint can omit it.
   */
  enabled?: boolean
}

/**
 * `GET /api/stocks/{ticker}/indicators` — historical indicator values and
 * the resulting BUY/SELL/HOLD signal for each daily bar
 * (docs/architecture/API.md#get-apistocksstickerindicators). Deliberately
 * generic (not `PriceChart`-specific): keyed and shaped the same way as
 * `useStockHistory` so both `PriceChart` (EMA/signal overlay) and
 * `OscillatorChart` (stochastic_k/force_index_2ema/macd_histogram panes,
 * frontend-oscillator-chart) reuse this same hook rather than each feature
 * writing its own `useQuery` wrapper around the same endpoint — see this
 * task's (frontend-chart-signal-overlay) decisions entry. Calling it twice
 * with the same `ticker`/`range` (as those two components do when both
 * mounted together) addresses the same TanStack Query cache entry, so the
 * underlying request is only actually made once. Typed to `ApiError` so
 * callers can pass `.error` straight into `common/ErrorState`, same
 * convention as useStockHistory/useStockAnalysis.
 */
export function useIndicatorHistory(
  ticker: string,
  { range }: UseIndicatorHistoryParams,
  { enabled = true }: UseIndicatorHistoryOptions = {},
) {
  return useQuery<IndicatorHistoryResponse, ApiError>({
    queryKey: stocksKeys.indicators(ticker, range),
    queryFn: () => getIndicatorHistory(ticker, { range }),
    enabled: ticker.length > 0 && enabled,
  })
}
