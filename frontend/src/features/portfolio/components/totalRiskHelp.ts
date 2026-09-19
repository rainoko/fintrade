/**
 * `common/MetricHelp` content for the "Total Risk (Open + Realized)" stat
 * shown on both RiskSummaryCard (Dashboard) and RiskPanel (Portfolio page).
 *
 * Shared between the two rather than duplicated inline: both StatCards
 * render the exact same combined `total_open_risk_pct` figure and need the
 * same breakdown explanation. Kept as a small local helper (not
 * `features/stocks/components/metricHelpContent.ts`'s shared registry
 * pattern) since only these two call sites need it -- see this task's
 * `decisions` entry.
 */

export interface TotalRiskHelpContent {
  metricLabel: string
  definition: string
  elderContext: string
  valueInterpretation: string
}

/**
 * `totalOpenRiskPct` is the already-combined total (docs/Analyse.md §7's
 * two-part 6% Rule: this month's realized losses plus open-position risk --
 * see `app.api.routers.portfolio.get_risk`'s `total_risk = open_risk +
 * realized_losses_this_month`), so the open-position-only portion is
 * recovered here as `totalOpenRiskPct - realizedLossesThisMonthPct` rather
 * than requiring a third backend field just for display.
 */
export function totalRiskHelp(
  totalOpenRiskPct: number,
  realizedLossesThisMonthPct: number,
): TotalRiskHelpContent {
  const openPositionRiskPct = totalOpenRiskPct - realizedLossesThisMonthPct

  return {
    metricLabel: 'Total Risk (Open + Realized)',
    definition:
      "The book's actual 6% Rule total: this calendar month's realized losses from closed " +
      'trades, plus the risk still outstanding in your open positions (each position’s ' +
      'distance from entry to its protective stop, sized by quantity).',
    elderContext:
      "Dr. Elder's 6% Rule (docs/Analyse.md §7) caps both halves combined at 6% of " +
      'equity for the current month -- a string of stopped-out losses earlier this month ' +
      'counts against the same limit as risk sitting in positions you still hold, even if ' +
      "every position you hold today is individually fine.",
    valueInterpretation:
      `${openPositionRiskPct.toFixed(2)}% from open positions + ` +
      `${realizedLossesThisMonthPct.toFixed(2)}% from this month's realized losses = ` +
      `${totalOpenRiskPct.toFixed(2)}% total.`,
  }
}
