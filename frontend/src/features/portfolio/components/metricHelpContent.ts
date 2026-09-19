/**
 * Help content for the "A-trade" grade metrics shown on `TradeJournalPanel`
 * (Elder ch. 55 "Is This an A-Trade?", docs/Analyse.md §7) — same registry
 * pattern as `features/stocks/components/metricHelpContent.ts` (one entry
 * per metric, each grounded in a specific docs/Analyse.md section, paired
 * with its own `interpretValue` function fed to `common/MetricHelp`), kept
 * as a separate file under `features/portfolio/` rather than added to the
 * stocks one: that file's own doc comment scopes it to "every metric shown
 * on StockDetailPage", and every entry below references a portfolio/trade
 * domain concept (a closed trade's buy/sell/entry-day-channel grade), not a
 * Triple Screen/confidence-scoring one — the same feature-vs-feature
 * placement test Frontend.md §3 applies to components/hooks applies here
 * too (see the frontend-trade-journal task's `decisions` entry).
 *
 * Each grade's `interpretValue` handles `null` explicitly (rather than
 * `common/MetricHelp`'s generic "omit this prop" contract) since a null
 * grade here is a specific, explainable case per API.md
 * (`GET /api/portfolio/closed-trades`) — the ticker's history doesn't reach
 * back far enough, that day was dropped as malformed, or (trade grade only)
 * the entry date falls inside the Autoenvelope's ~100-bar warm-up window —
 * not "no interpretation available" the way e.g. IndicatorsPanel's
 * `isKnown` guard treats a stale/malformed latest bar.
 */

export const buyGradeHelp = {
  metricLabel: 'Buy Grade',
  definition:
    '(entry day’s high − buy price) / (entry day’s high − entry day’s low), as a percentage -- how close to that day’s low the buy actually was (Elder ch. 55 "Is This an A-Trade?", docs/Analyse.md §7).',
  elderContext:
    'One of three formulas Elder uses to grade a *completed* trade by how much of what was realistically available got captured, not raw P&L alone -- a profitable trade can still score poorly here if it was bought well above that day’s low. A buy grade over 50% is "very good" (docs/ideas.md ch. 55).',
  interpretValue(buyGradePct: number | null): string {
    if (buyGradePct === null) {
      return 'Not available for this trade -- the entry day’s own high/low couldn’t be found in this ticker’s currently-fetchable daily history (it may predate that history, or that bar was unusable), so this grade can’t be computed right now.'
    }
    const upFromLow = 100 - buyGradePct
    return `You bought at ${upFromLow.toFixed(1)}% up the entry day’s high-low range (a ${buyGradePct.toFixed(1)}% buy grade) -- Elder considers a buy grade over 50% (bought in the lower half of that day’s range) "very good".`
  },
}

export const sellGradeHelp = {
  metricLabel: 'Sell Grade',
  definition:
    '(sell price − exit day’s low) / (exit day’s high − exit day’s low), as a percentage -- how close to that day’s high the sell actually was (Elder ch. 55, docs/Analyse.md §7).',
  elderContext:
    'The sell-side counterpart to Buy Grade: grades the exit by how much of that day’s upside was captured, not just whether the trade was profitable overall. A sell grade over 50% is "very good" (docs/ideas.md ch. 55).',
  interpretValue(sellGradePct: number | null): string {
    if (sellGradePct === null) {
      return 'Not available for this trade -- the exit day’s own high/low couldn’t be found in this ticker’s currently-fetchable daily history (it may predate that history, or that bar was unusable), so this grade can’t be computed right now.'
    }
    return `You sold at ${sellGradePct.toFixed(1)}% up the exit day’s high-low range -- Elder considers a sell grade over 50% "very good".`
  },
}

export const tradeGradeHelp = {
  metricLabel: 'Trade Grade',
  definition:
    '(sell price − buy price) / (channel high − channel low, measured on the entry day), as a percentage -- the trade’s actual gain as a fraction of the entry day’s Autoenvelope/channel height (docs/Analyse.md §4, §7).',
  elderContext:
    'Elder’s preferred way to grade a completed trade overall: it measures the gain against how wide that day’s realistic channel move was, not the raw dollar/percent return alone -- a highly profitable trade can still be a "C" if the channel was wide, and a barely-profitable one can be an "A" if it captured most of a narrow channel. Roughly 30%+ capture is an "A" trade, ~10% a "C" trade (Elder ch. 55, docs/ideas.md ch. 55/ch. 33’s own preview).',
  interpretValue(tradeGradePct: number | null): string {
    if (tradeGradePct === null) {
      return 'Not available for this trade -- the entry day’s channel (Autoenvelope) bounds aren’t currently computable, either because this ticker’s fetched daily history doesn’t reach back to the entry date, or because the entry date falls inside the channel’s own ~100-bar warm-up window.'
    }
    return `This trade captured ${tradeGradePct.toFixed(1)}% of the entry day’s channel height -- Elder rates roughly 30%+ capture an "A" trade, and around 10% a "C" trade.`
  },
}
