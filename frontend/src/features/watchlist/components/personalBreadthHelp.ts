import type { BreadthResponse } from '../../../api/watchlist'

/**
 * `common/MetricHelp` content for `PersonalBreadthCard`'s "Personal Breadth"
 * stat (`GET /api/watchlist/breadth`, docs/Analyse.md's "Personal breadth
 * proxy" section) — same registry-style pattern as
 * `features/portfolio/components/totalRiskHelp.ts` (a small local helper
 * function producing dynamic `valueInterpretation` text from the live
 * response, rather than a static string), kept local to this one call site
 * rather than added to `features/stocks/components/metricHelpContent.ts`'s
 * shared registry — that file's own doc comment scopes it to "every metric
 * shown on StockDetailPage", and this metric is watchlist/portfolio-page
 * scoped instead (same feature-vs-feature placement test Frontend.md §3
 * applies to components/hooks applies here too).
 *
 * The `elderContext` is deliberately explicit that this is an
 * *approximation*, not real market breadth — the task description's own
 * instruction ("be honest about this distinction ... rather than letting it
 * read as more authoritative than it is") and docs/Analyse.md's own framing
 * ("this is explicitly a *personal* breadth proxy, reflecting only the
 * tickers this particular user happens to be tracking, not the market as a
 * whole").
 */

export interface PersonalBreadthHelpContent {
  metricLabel: string
  definition: string
  elderContext: string
  valueInterpretation: string
}

export function personalBreadthHelp(data: BreadthResponse): PersonalBreadthHelpContent {
  const {
    tracked_ticker_count: trackedTickerCount,
    bullish_count: bullishCount,
    bearish_count: bearishCount,
    neutral_count: neutralCount,
    unavailable_count: unavailableCount,
    bullish_pct: bullishPct,
    bearish_pct: bearishPct,
    neutral_pct: neutralPct,
  } = data
  const computable = bullishCount + bearishCount + neutralCount

  let valueInterpretation: string
  if (trackedTickerCount === 0) {
    valueInterpretation =
      'Nothing tracked yet -- add a ticker to your watchlist or portfolio to see a personal breadth breakdown.'
  } else if (computable === 0) {
    valueInterpretation = `None of your ${trackedTickerCount} tracked ticker${trackedTickerCount === 1 ? '' : 's'} has a computable Tide trend right now.`
  } else {
    const unavailableClause =
      unavailableCount > 0
        ? ` (${unavailableCount} of ${trackedTickerCount} tracked ticker${unavailableCount === 1 ? '' : 's'} unavailable right now, excluded from these percentages)`
        : ''
    valueInterpretation =
      `${bullishCount} of ${computable} computable ticker${computable === 1 ? '' : 's'} (${bullishPct.toFixed(1)}%) are currently BULLISH, ` +
      `${bearishCount} (${bearishPct.toFixed(1)}%) BEARISH, ${neutralCount} (${neutralPct.toFixed(1)}%) NEUTRAL${unavailableClause}.`
  }

  return {
    metricLabel: 'Personal Breadth',
    definition:
      'The share of your own tracked tickers (this watchlist plus your portfolio, deduplicated) whose weekly Screen 1 (Tide) trend is currently BULLISH, BEARISH, or NEUTRAL.',
    elderContext:
      "Dr. Elder tracks broad market breadth (New High-New Low Index, % of stocks above their 50-day MA, the Advance/Decline line -- ch. 34-36) because general market trends drive as much as half of any individual stock's movement. This app has no broad market universe to compute the real thing from (e.g. the full S&P 500), so this is a cheaper, personal-scale approximation instead: it only reflects the handful of tickers *you* happen to be watching or holding, not the market as a whole -- treat it as a rough personal-context signal, not true market breadth.",
    valueInterpretation,
  }
}
