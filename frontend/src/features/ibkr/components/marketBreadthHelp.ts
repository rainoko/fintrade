import type { MarketBreadthData } from '../hooks/useMarketBreadth'
import { formatNullableNumber, formatSignedSpread } from '../../../utils/format'

/**
 * `common/MetricHelp` content for `MarketBreadthCard` (Elder ch. 34-36's
 * real, broad-market breadth indicators, approximated via the IBKR scanner
 * — docs/Analyse.md's "IBKR-scanner breadth approximation" section). Same
 * registry-style pattern as `features/watchlist/components/
 * personalBreadthHelp.ts` (a small local helper producing dynamic
 * `valueInterpretation` text from the live response), kept local to this
 * one call site for the same reason that file gives: this metric isn't
 * shown on `StockDetailPage`, so `features/stocks/components/
 * metricHelpContent.ts`'s shared registry doesn't apply.
 *
 * Deliberately explicit — in both `elderContext` and `valueInterpretation`
 * — that `count`/the spread below are a *bounded, single-scan-result-count*
 * approximation, never comparable to ch. 34's own full-market numeric
 * thresholds (weekly NH-NL ±4,000/+2,500, 20-day NH-NL −500): showing a
 * raw number without that caveat would read as more authoritative than it
 * is, the same concern `personalBreadthHelp.ts` and this app's own
 * `docs/Analyse.md` section already raise for this exact endpoint.
 */

export interface MarketBreadthHelpContent {
  metricLabel: string
  definition: string
  elderContext: string
  valueInterpretation: string | null
}

export function marketBreadthHelp(data: MarketBreadthData | null): MarketBreadthHelpContent {
  const definition =
    "A same-day count of IBKR-scanner \"Top % Gainers\" vs. \"Top % Losers\" matches, used as a crude proxy for Elder's Advance/Decline line, plus 5-day/20-day rolling sums of that count."
  const elderContext =
    "Dr. Elder tracks real, broad-market breadth (the New High-New Low Index, % of stocks above their 50-day MA, the Advance/Decline line -- ch. 34-36) because general market trends drive as much as half of any individual stock's movement. This app has no genuine full-market data feed to compute those literally, so this reading instead counts how many names IBKR's own market scanner returns for a single 'top % gainers' vs. 'top % losers' scan -- a bounded, capped shortlist, not a true full-market count. Treat rising/falling and which side currently has more names as the useful signal, not the raw numbers themselves: they are not comparable to ch. 34's own numeric thresholds (e.g. weekly NH-NL of ±4,000), which assume real full-market magnitudes far beyond what one capped scan run can ever report."

  if (!data) {
    return { metricLabel: 'Market Breadth (IBKR Scanner)', definition, elderContext, valueInterpretation: null }
  }

  const { advance, decline } = data
  const valueInterpretation =
    `Today: ${formatNullableNumber(advance.count)} top-gainer matches vs. ${formatNullableNumber(decline.count)} top-loser matches. ` +
    `5-day spread: ${formatSignedSpread(advance.rolling_5d, decline.rolling_5d, 'not enough history yet')}. ` +
    `20-day spread: ${formatSignedSpread(advance.rolling_20d, decline.rolling_20d, 'not enough history yet')}.`

  return {
    metricLabel: 'Market Breadth (IBKR Scanner)',
    definition,
    elderContext,
    valueInterpretation,
  }
}
