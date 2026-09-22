// Shared TanStack Query key convention for the ibkr feature. Currently a
// single read-only query (GET /api/ibkr/status) with nothing else to
// namespace against yet, but kept as its own file rather than an inline
// array literal in useIbkrStatus.ts for consistency with every other
// feature's queryKeys.ts (watchlist, portfolio, stocks).
export const ibkrKeys = {
  status: ['ibkr', 'status'] as const,
}
