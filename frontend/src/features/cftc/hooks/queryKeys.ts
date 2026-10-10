// Shared TanStack Query key conventions for the cftc feature.
//
// `cot` is a single fixed key (no parameters) — `GET /api/cftc/cot` always
// returns the same fixed 5-market set, there's no per-market query to key
// against, and this app has exactly one consumer (`CftcCotCard`) today —
// mirroring `ibkrKeys.breadthAdvanceDecline`'s identical single-fixed-key
// shape for the same reason.
export const cftcKeys = {
  cot: ['cftc', 'cot'] as const,
}
