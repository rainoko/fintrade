import type { InsiderClusterOut } from '../api/stocks'

/**
 * Sorts insider-transaction clusters most-recent-`window_end_date`-first.
 * Extracted per frontend-insider-clusters-badge-followups (PR #195 review)
 * -- this comparator used to be duplicated verbatim between
 * `FundamentalDataPanel.tsx`'s `InsiderClusterCallouts` and
 * `metricHelpContent.ts`'s `insiderClustersHelp.interpretValue`, so a future
 * correctness fix to it (e.g. a tie-break, or an equal-date edge case)
 * could silently apply to only one call site, leaving the callout list and
 * the MetricHelp text disagree on cluster order for the same ticker.
 * Returns a new array; never mutates `clusters`.
 */
export function sortClustersByRecentWindowEnd(
  clusters: readonly InsiderClusterOut[],
): InsiderClusterOut[] {
  return [...clusters].sort((a, b) =>
    a.window_end_date < b.window_end_date ? 1 : -1,
  )
}
