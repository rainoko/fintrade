import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import {
  getYesterdayTradingSuggestion,
  type YesterdayTradingSuggestionOut,
} from '../../../api/homework'
import { homeworkKeys } from './queryKeys'

/**
 * `GET /api/daily-homework/yesterday-trading-suggestion` — a suggested
 * (never authoritative) "how did I trade yesterday?" score derived from
 * yesterday's closed-trade P&L, used to pre-fill (not auto-submit)
 * `DailyHomeworkForm`'s `yesterday_trading_score` field when today's entry
 * hasn't been recorded yet (docs/architecture/API.md).
 */
export function useYesterdayTradingSuggestion() {
  return useQuery<YesterdayTradingSuggestionOut, ApiError>({
    queryKey: homeworkKeys.yesterdaySuggestion,
    queryFn: getYesterdayTradingSuggestion,
  })
}
