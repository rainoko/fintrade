import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { updateTradingMode, type TradingModeIn, type TradingModeOut } from '../../../api/settings'

/**
 * `PUT /api/settings/trading-mode` (docs/architecture/API.md). On success,
 * invalidates *every* cached query (`queryClient.invalidateQueries()` with
 * no filter), not just `settingsKeys.tradingMode` — unlike this app's other
 * mutations, which invalidate only the one or two query keys their write
 * actually affects (deliberately avoiding cross-feature query-key coupling,
 * see `features/watchlist/hooks/queryKeys.ts`'s own comment on why breadth
 * doesn't invalidate on a portfolio-side edit). The trading mode is a
 * single global setting that `GET /api/stocks/{ticker}/analysis`,
 * `GET /api/stocks/{ticker}/indicators`, `GET /api/watchlist`,
 * `GET /api/watchlist/breadth`, `GET /api/portfolio`, and
 * `GET /api/portfolio/risk` all read (docs/architecture/API.md's
 * `GET /api/settings/trading-mode` section) — switching it stale-dates
 * literally every other domain's cached signal/confidence/risk data at
 * once, not a narrow, identifiable slice the way e.g. adding a position
 * only affects portfolio+risk. Scoping this to an explicit list of query
 * keys would require this one feature to import every other feature's
 * `queryKeys.ts` (a worse cross-feature coupling than the blanket
 * invalidation this uses instead) and would silently stop covering a future
 * mode-aware endpoint added without also updating this list. See this
 * task's `decisions` entry.
 */
export function useUpdateTradingMode() {
  const queryClient = useQueryClient()

  return useMutation<TradingModeOut, ApiError, TradingModeIn>({
    mutationFn: updateTradingMode,
    onSuccess: () => {
      void queryClient.invalidateQueries()
    },
  })
}
