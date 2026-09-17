// Shared TanStack Query key conventions for the stocks feature, mirroring
// features/portfolio/hooks/queryKeys.ts's convention. `analysis` is keyed by
// ticker since each ticker's analysis is an independent query (unlike
// portfolio's single-account key). `history` is additionally keyed by
// `range`/`interval` so changing either param addresses a distinct cache
// entry rather than reusing a stale response from a different query — see
// useStockHistory.ts.
export const stocksKeys = {
  analysis: (ticker: string) => ['stocks', 'analysis', ticker] as const,
  history: (ticker: string, range: string, interval: string) =>
    ['stocks', 'history', ticker, range, interval] as const,
}
