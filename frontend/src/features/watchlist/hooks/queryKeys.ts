// Shared TanStack Query key conventions for the watchlist feature, mirroring
// features/portfolio/hooks/queryKeys.ts's single-top-level-key convention.
// Unlike portfolio (which nests a `risk` key so invalidating `all` also
// invalidates it via prefix-matching, see that file's own decision note),
// the watchlist feature has exactly one query (the list) and no derived
// sub-resource to keep in sync, so a single key is sufficient.
export const watchlistKeys = {
  all: ['watchlist'] as const,
}
