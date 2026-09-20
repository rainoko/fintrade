// Shared TanStack Query key conventions for the watchlist feature.
//
// `breadth` nests under `all`, mirroring features/portfolio/hooks/
// queryKeys.ts's `risk`/`closedTrades` nesting: useAddWatchlistItem/
// useRemoveWatchlistItem's existing `invalidateQueries({ queryKey:
// watchlistKeys.all })` therefore also refetches the breadth query via
// TanStack Query's prefix-matching invalidation, with neither mutation hook
// needing to import anything from useWatchlistBreadth. This does *not*
// cover a portfolio-side edit (adding/removing a position on the Portfolio
// page invalidates only `portfolioKeys.all`, a separate top-level key) even
// though breadth's own denominator spans the watchlist+portfolio union --
// Coupling the watchlist feature's query keys to the portfolio feature's
// mutations (or vice versa) would be a worse cross-feature dependency than
// the breadth widget being up to `staleTime` (60s, main.tsx) stale after a
// portfolio-only edit made on a different page; see the
// frontend-breadth-widget task's `decisions` entry.
//
// `add` is a *mutation* key, not a query key -- it exists purely so
// WatchlistTable can observe useAddWatchlistItem's shared mutation-cache
// entry via `useMutationState({ filters: { mutationKey: watchlistKeys.add } })`
// to know which ticker (if any) is currently being added, without
// AddTickerForm (which owns the mutation) needing to be lifted or have its
// mutation object prop-drilled down to its WatchlistTable sibling (see
// frontend-watchlist-add-skeleton's `decisions`).
export const watchlistKeys = {
  all: ['watchlist'] as const,
  breadth: ['watchlist', 'breadth'] as const,
  add: ['watchlist', 'add'] as const,
}
