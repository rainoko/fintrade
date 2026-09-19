// Shared TanStack Query key conventions for the watchlist feature, mirroring
// features/portfolio/hooks/queryKeys.ts's single-top-level-key convention.
// Unlike portfolio (which nests a `risk` key so invalidating `all` also
// invalidates it via prefix-matching, see that file's own decision note),
// the watchlist feature has exactly one query (the list) and no derived
// sub-resource to keep in sync, so a single query key is sufficient.
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
  add: ['watchlist', 'add'] as const,
}
