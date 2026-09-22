// Shared TanStack Query key conventions for the scanner feature.
//
// `run` is a *mutation* key (matching watchlist/hooks/queryKeys.ts's own
// `add` mutation-key precedent) — POST /api/ibkr/scanner/run has no cached
// query counterpart to invalidate (a scan result isn't read anywhere else,
// unlike watchlist/portfolio data), so this key exists only in case a future
// component ever needs to observe the run mutation's shared cache entry the
// way WatchlistTable observes useAddWatchlistItem's.
export const scannerKeys = {
  params: ['ibkr', 'scanner', 'params'] as const,
  run: ['ibkr', 'scanner', 'run'] as const,
}
