import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { updateTradingMode, type TradingModeIn, type TradingModeOut } from '../../../api/settings'
import { portfolioKeys } from '../../portfolio/hooks/queryKeys'
import { stocksKeys } from '../../stocks/hooks/queryKeys'
import { watchlistKeys } from '../../watchlist/hooks/queryKeys'

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
 */
export function useUpdateTradingMode() {
  const queryClient = useQueryClient()

  return useMutation<TradingModeOut, ApiError, TradingModeIn>({
    mutationFn: updateTradingMode,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: stocksKeys.all })
      void queryClient.invalidateQueries({ queryKey: watchlistKeys.all })
      void queryClient.invalidateQueries({ queryKey: portfolioKeys.all })
    },
  })
}
