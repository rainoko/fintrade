// Shared TanStack Query key conventions for the stocks feature, mirroring
// features/portfolio/hooks/queryKeys.ts's convention. `analysis` is keyed by
// ticker since each ticker's analysis is an independent query (unlike
// portfolio's single-account key). `history`'s key lands with the
// frontend-stock-history-chart task, which owns useStockHistory.
export const stocksKeys = {
  analysis: (ticker: string) => ['stocks', 'analysis', ticker] as const,
}
