import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { getTradingMode, type TradingModeOut } from '../../../api/settings'
import { settingsKeys } from './queryKeys'

/**
 * `GET /api/settings/trading-mode` (docs/architecture/API.md) — the
 * currently-active global trading mode plus the last-configured day-trader
 * timeframe triple. Used by `TradingModeSettingsForm` to pre-fill the form
 * with whatever is already persisted.
 */
export function useTradingMode() {
  return useQuery<TradingModeOut, ApiError>({
    queryKey: settingsKeys.tradingMode,
    queryFn: getTradingMode,
  })
}
