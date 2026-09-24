// Shared TanStack Query key conventions for the portfolio feature.
//
// Decision (frontend-portfolio-page task): `risk` nests under `all`
// (['portfolio', 'risk'] vs. ['portfolio']) specifically so that
// `queryClient.invalidateQueries({ queryKey: portfolioKeys.all })` — used by
// useAddPosition/useDeletePosition below — also invalidates the
// portfolio-risk query via TanStack Query's default prefix-matching
// invalidation, without this feature needing to import anything from
// usePortfolioRisk (which doesn't exist yet; it lands in the
// frontend-portfolio-risk-panel task). Rejected alternative: two unrelated
// top-level keys (['portfolio'] and ['portfolioRisk']) invalidated via two
// explicit calls — this would silently stop invalidating risk data the
// moment either hook's key changed without the other being updated in
// lockstep, whereas the prefix relationship makes that impossible by
// construction.
// `closedTrades` nests under `all` for the same reason `risk` does above:
// `useDeletePosition`'s invalidation of `portfolioKeys.all` records a new
// `closed_trades` row (API.md's `DELETE /api/portfolio/positions/{id}`), so
// the trade journal needs to refetch right alongside the portfolio/risk
// queries after a delete — nesting under the same prefix gets that for free
// via TanStack Query's prefix-matching invalidation, with no extra call
// needed in useDeletePosition itself (frontend-trade-journal's `decisions`
// entry).
// `dueForFollowUpTrades` nests one level deeper under `closedTrades` (rather
// than being a sibling top-level key) since it's the *same* underlying
// resource with `?due_for_follow_up=true` applied (API.md) -- nesting it
// means `useRecordFollowUpReview`'s invalidation of `portfolioKeys.all`
// refreshes both the unfiltered journal table and the due-list in one call,
// with no separate explicit invalidation needed, same prefix-matching
// rationale as `risk`/`closedTrades` above (frontend-trade-journal-followup-review
// task's `decisions` entry).
export const portfolioKeys = {
  all: ['portfolio'] as const,
  risk: ['portfolio', 'risk'] as const,
  closedTrades: ['portfolio', 'closed-trades'] as const,
  dueForFollowUpTrades: ['portfolio', 'closed-trades', 'due-for-follow-up'] as const,
}
