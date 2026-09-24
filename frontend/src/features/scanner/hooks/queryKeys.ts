// Shared TanStack Query key conventions for the scanner feature.
//
// `run` is a *mutation* key (matching watchlist/hooks/queryKeys.ts's own
// `add` mutation-key precedent) — POST /api/ibkr/scanner/run has no cached
// query counterpart to invalidate (a scan result isn't read anywhere else,
// unlike watchlist/portfolio data), so this key exists only in case a future
// component ever needs to observe the run mutation's shared cache entry the
// way WatchlistTable observes useAddWatchlistItem's.
//
// `addToWatchlist` is also a *mutation* key: ScannerAddToWatchlistButton
// passes it to `useAddWatchlistItem({ mutationKey: scannerKeys.addToWatchlist })`
// instead of letting that hook fall back to its own default
// `watchlistKeys.add`. `useMutation`'s cache is a single, app-wide,
// per-`QueryClient` store keyed only by `mutationKey` — it isn't scoped by
// which page/component dispatched `mutate()` — so a Scanner-page add left on
// the watchlist feature's own default key would be indistinguishable, from
// WatchlistTable's `useMutationState({ filters: { mutationKey:
// watchlistKeys.add } })` point of view, from an add dispatched by the
// Watchlist page's own AddTickerForm, rendering a phantom pending-add
// skeleton row for a ticker the Watchlist page's own user never touched
// (round-4 regression, PR #243, frontend-market-scanner-page).
export const scannerKeys = {
  params: ['ibkr', 'scanner', 'params'] as const,
  run: ['ibkr', 'scanner', 'run'] as const,
  addToWatchlist: ['ibkr', 'scanner', 'addToWatchlist'] as const,
}
