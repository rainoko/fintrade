import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { getStockAnalysis, type AnalysisResponse } from '../../../api/stocks'
import { stocksKeys } from '../../stocks/hooks/queryKeys'

/**
 * Fetches `GET /api/stocks/{ticker}/analysis` for a single held position's
 * ticker, for the sole purpose of reading its `profit_target` field
 * (`RiskPanel`'s Profit Target column, via `PositionProfitTargetCell`).
 *
 * `RiskResponse`/`PositionOut` deliberately don't carry `profit_target`
 * themselves -- see the `backend-profit-target` task's own `decisions`
 * entry: it's scoped to a fresh-BUY-signal concept computed against
 * `AnalysisResponse`, not a held-position one, and `RiskPosition` has no
 * `signal` field to gate a BUY-only computation on anyway. Rather than
 * requesting a backend change to add it there, this reuses the exact same
 * `GET /.../analysis` endpoint `StockDetailPage`/`PriceChart` already call
 * for that ticker -- see this task's own `decisions` entry for why this is
 * a deliberate, narrow exception to "features own their hooks"
 * (Frontend.md §3): it imports `features/stocks/hooks/queryKeys.ts`'s
 * `stocksKeys.analysis` key (a plain, side-effect-free config object, not a
 * hook or component) rather than duplicating the literal key array, so a
 * ticker the user has already opened on its own Stock Detail page shares
 * that cached response here instead of firing a second identical request --
 * and so the two can never silently drift apart the way a hand-duplicated
 * key literal could.
 *
 * `enabled` should be `signal === 'BUY'` at the call site: `profit_target`
 * is contractually null for every other signal (docs/Analyse.md §7), so
 * skipping the fetch entirely for a HOLD/SELL/unknown-signal position
 * avoids firing an analysis request whose only interesting field is
 * guaranteed absent.
 */
export function usePositionProfitTarget(ticker: string, enabled: boolean) {
  return useQuery<AnalysisResponse, ApiError>({
    queryKey: stocksKeys.analysis(ticker),
    queryFn: () => getStockAnalysis(ticker),
    enabled: enabled && ticker.length > 0,
    staleTime: 60_000,
  })
}
