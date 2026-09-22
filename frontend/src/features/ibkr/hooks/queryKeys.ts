// Shared TanStack Query key conventions for the ibkr feature.
//
// `breadthAdvanceDecline` is a single fixed key (not parameterized by
// series_key) because `useMarketBreadth` composes both halves of the
// Advance/Decline reading (docs/tasks/frontend-market-breadth-widget.json's
// `decisions` entry) into one query result — there's exactly one consumer
// (`MarketBreadthCard`) and no per-series query anywhere else to key
// against yet, unlike `watchlistKeys.breadth`'s single-endpoint nesting.
export const ibkrKeys = {
  status: ['ibkr', 'status'] as const,
  breadthAdvanceDecline: ['ibkr', 'breadth', 'advance-decline'] as const,
}
