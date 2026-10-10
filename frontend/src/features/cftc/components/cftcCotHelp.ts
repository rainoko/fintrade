import type { CFTCCOTMarketOut, CFTCCOTResponse } from '../../../api/cftc'

/**
 * `common/MetricHelp` content for `CftcCotCard` (Elder ch. 37's Commitments
 * of Traders framing -- docs/ideas.md's ch. 37 entry, docs/Analyse.md's
 * short-interest/insider-transactions rows a few lines up from it). Same
 * local-registry pattern `marketBreadthHelp.ts`/`personalBreadthHelp.ts`
 * establish: a small helper producing dynamic `valueInterpretation` text
 * from the live response, kept local to this one call site rather than
 * added to `features/stocks/components/metricHelpContent.ts`'s shared
 * registry, since this metric isn't shown on `StockDetailPage` -- it's a
 * futures-market-context widget, not a per-ticker one.
 *
 * Deliberately explicit that the COT Index is a *relative, trailing-window*
 * reading (0 = at/below its own trailing 52-week low, 100 = at/above its own
 * trailing 52-week high) rather than an absolute bullish/bearish percentage
 * -- the same "read current positioning against historical norms rather
 * than an absolute level" framing Elder's own ch. 37 text uses, and the
 * exact computation `backend-cftc-cot-data`'s `decisions` entry records.
 */

export interface CftcCotHelpContent {
  metricLabel: string
  definition: string
  elderContext: string
  valueInterpretation: string | null
}

function describeExtreme(
  markets: CFTCCOTMarketOut[],
  pick: 'commercial_cot_index_52w',
): string | null {
  const withIndex = markets.filter(
    (market): market is CFTCCOTMarketOut & { commercial_cot_index_52w: number } =>
      market[pick] !== null,
  )
  if (withIndex.length === 0) {
    return null
  }
  if (withIndex.length === 1) {
    const only = withIndex[0]
    return `${only.display_name}'s commercials sit at a commercial COT Index of ${only[pick].toFixed(0)} -- the only market with a computable reading right now.`
  }
  const highest = withIndex.reduce((a, b) => (b[pick] > a[pick] ? b : a))
  const lowest = withIndex.reduce((a, b) => (b[pick] < a[pick] ? b : a))
  if (highest[pick] === lowest[pick]) {
    // Every computable market shares the same value -- `reduce`'s `>`/`<`
    // comparisons both keep the first element on a tie, so `highest` and
    // `lowest` are the same object here, but that does NOT mean it's the
    // only computable market (see the `length === 1` branch above for that
    // case) -- 2+ markets can independently land on the same boundary value
    // (e.g. two markets each sitting at their own trailing 52-week extreme),
    // so name all of them rather than singling one out as unique.
    const names = withIndex.map((market) => market.display_name).join(', ')
    return `Commercials are tied at a commercial COT Index of ${highest[pick].toFixed(0)} across every market with a computable reading right now (${names}).`
  }
  return (
    `Commercials are currently most bullish (relative to their own trailing 52-week range) in ${highest.display_name} ` +
    `(commercial COT Index ${highest[pick].toFixed(0)}) and least bullish in ${lowest.display_name} (${lowest[pick].toFixed(0)}).`
  )
}

/**
 * Unlike `marketBreadthHelp`/`personalBreadthHelp` (which take a nullable
 * snapshot so the same helper covers an unavailable/disabled state), this
 * one always takes a real `CFTCCOTResponse` -- `CftcCotCard` has no
 * "gateway disabled" fallback state of its own to represent (unlike IBKR's
 * optional integration), only loading/error/data, and the loading/error
 * cases never reach this helper at all (see `CftcCotCard.tsx`).
 */
export function cftcCotHelp(data: CFTCCOTResponse): CftcCotHelpContent {
  return {
    metricLabel: 'Commitments of Traders (COT)',
    definition:
      'Weekly CFTC Commitments of Traders positioning (long/short/net) for commercials, large speculators, and small speculators, for 5 fixed major futures markets (Euro, Yen, Oil, Gold, Bonds) -- plus a 52-week "COT Index" for each group, scaling its current net position from 0 (at/below its own trailing 52-week low) to 100 (at/above its own trailing 52-week high).',
    elderContext:
      "Dr. Elder's ch. 37 framing: follow commercials (historically the successful group), fade small speculators (historically the unsuccessful group), and read current positioning against historical norms rather than an absolute level -- a raw net-position count isn't comparable across time as overall open interest grows or shrinks, which is exactly what the COT Index corrects for. This is futures-market context only -- it isn't wired into any per-stock-ticker BUY/SELL/HOLD signal, the same way insider transactions and short interest are shown as context without feeding confidence.",
    valueInterpretation: describeExtreme(data.markets, 'commercial_cot_index_52w'),
  }
}
