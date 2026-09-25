import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { updateTradingMode, type TradingModeIn, type TradingModeOut } from '../../../api/settings'
import { portfolioKeys } from '../../portfolio/hooks/queryKeys'
import { stocksKeys } from '../../stocks/hooks/queryKeys'
import { watchlistKeys } from '../../watchlist/hooks/queryKeys'
import { settingsKeys } from './queryKeys'

/**
 * `PUT /api/settings/trading-mode` (docs/architecture/API.md). On success,
 * invalidates the `stocks`/`watchlist`/`portfolio` query-key prefixes —
 * scoped to the exact set of endpoints docs/architecture/API.md documents
 * as trading-mode-dependent (`GET /api/stocks/{ticker}/analysis`,
 * `GET /api/stocks/{ticker}/indicators` under `stocksKeys.all`;
 * `GET /api/watchlist`, `GET /api/watchlist/breadth` under
 * `watchlistKeys.all`; `GET /api/portfolio`, `GET /api/portfolio/risk`
 * under `portfolioKeys.all`) — rather than the app-wide, unfiltered
 * `queryClient.invalidateQueries()` this hook used before
 * frontend-day-trader-timeframe-mode-settings-followups. Reuses each
 * feature's own `xKeys.all` prefix constant, the same convention
 * useAddPosition/useAddWatchlistItem already use for their own
 * single-feature invalidations, rather than a second, independently
 * hand-maintained literal key list — see this task's `decisions` entry for
 * why this was judged an acceptable amount of cross-feature coupling where
 * the originally-recorded blanket-invalidation decision judged importing
 * every other feature's query keys too costly.
 *
 * Also invalidates `settingsKeys.tradingMode` itself — the query this same
 * mutation's own `useTradingMode()` reads to pre-fill this form. The
 * original unfiltered `queryClient.invalidateQueries()` covered this key
 * for free; the scoped stocks/watchlist/portfolio-only replacement above
 * dropped it, which meant a client-side navigation away from and back to
 * Settings within the global 60s `staleTime` window (`main.tsx`) re-mounted
 * the form from the stale pre-save cache even though the backend had
 * already persisted the new mode/triple (PR #328 review finding). See this
 * task's `decisions` entry for how this was verified.
 */
export function useUpdateTradingMode() {
  const queryClient = useQueryClient()

  return useMutation<TradingModeOut, ApiError, TradingModeIn>({
    mutationFn: updateTradingMode,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: stocksKeys.all })
      void queryClient.invalidateQueries({ queryKey: watchlistKeys.all })
      void queryClient.invalidateQueries({ queryKey: portfolioKeys.all })
      void queryClient.invalidateQueries({ queryKey: settingsKeys.tradingMode })
    },
  })
}
