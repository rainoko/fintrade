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
export const portfolioKeys = {
  all: ['portfolio'] as const,
  risk: ['portfolio', 'risk'] as const,
}
