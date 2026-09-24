import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import {
  getYesterdayTradingSuggestion,
  type YesterdayTradingSuggestionOut,
} from '../../../api/homework'
import { homeworkKeys } from './queryKeys'

export interface UseYesterdayTradingSuggestionOptions {
  /**
   * Lets a caller gate the request on something beyond "always fetch" --
   * `DailyHomeworkForm` uses this to skip the fetch entirely once today's
   * entry already exists and the suggestion is provably unused (same
   * `enabled:`-gating pattern as `useIndicatorHistory`/`useStockHistory`/
   * `useStockAnalysis`). Defaults to `true` so a caller with no such
   * constraint can omit it.
   */
  enabled?: boolean
}

/**
 * `GET /api/daily-homework/yesterday-trading-suggestion` — a suggested
 * (never authoritative) "how did I trade yesterday?" score derived from
 * yesterday's closed-trade P&L, used to pre-fill (not auto-submit)
 * `DailyHomeworkForm`'s `yesterday_trading_score` field when today's entry
 * hasn't been recorded yet (docs/architecture/API.md).
 */
export function useYesterdayTradingSuggestion({
  enabled = true,
}: UseYesterdayTradingSuggestionOptions = {}) {
  return useQuery<YesterdayTradingSuggestionOut, ApiError>({
    queryKey: homeworkKeys.yesterdaySuggestion,
    queryFn: getYesterdayTradingSuggestion,
    enabled,
  })
}
