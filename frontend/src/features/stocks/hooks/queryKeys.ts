// Shared TanStack Query key conventions for the stocks feature, mirroring
// features/portfolio/hooks/queryKeys.ts's convention. `analysis` is keyed by
// ticker since each ticker's analysis is an independent query (unlike
// portfolio's single-account key). `history` is additionally keyed by
// `range`/`interval` so changing either param addresses a distinct cache
// entry rather than reusing a stale response from a different query — see
// useStockHistory.ts. `indicators` is keyed by `range` only (no `interval`
// — GET /api/stocks/{ticker}/indicators has no such param, see
// useIndicatorHistory.ts), consistent with `history`'s range-keying
// convention per the frontend-chart-signal-overlay task's checklist.
//
// `all` is the shared top-level prefix every one of the above keys already
// nests under (`['stocks', ...]`) — added for
// frontend-day-trader-timeframe-mode-settings-followups so
// useUpdateTradingMode can invalidate every stocks-feature query via
// TanStack Query's own prefix-matching `invalidateQueries`, the same
// `xKeys.all` convention useAddPosition/useAddWatchlistItem already use for
// their own feature, without needing a second, independently-typed literal
// `['stocks']` array kept in sync by hand.
export const stocksKeys = {
  all: ['stocks'] as const,
  analysis: (ticker: string) => ['stocks', 'analysis', ticker] as const,
  history: (ticker: string, range: string, interval: string) =>
    ['stocks', 'history', ticker, range, interval] as const,
  indicators: (ticker: string, range: string) =>
    ['stocks', 'indicators', ticker, range] as const,
}
