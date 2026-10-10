import type { ProfitTargetOut } from '../../../api/stocks'
import {
  PROFIT_TARGET_DEFINITION,
  PROFIT_TARGET_ELDER_CONTEXT_SUFFIX,
} from '../../../utils/profitTargetHelpText'

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
 * not "no interpretation available" the way e.g. `isKnownNumber`
 * (`utils/format.ts`, used by `features/stocks/components/
 * metricHelpContent.ts`'s `interpretValue` functions that IndicatorsPanel
 * renders) treats a stale/malformed latest bar.
 */

/**
 * Profit target + reward:risk ratio help for `PositionProfitTargetCell`
 * (`RiskPanel`'s Profit Target column, `frontend-profit-target-display`,
 * docs/Analyse.md §7). A parallel entry to `features/stocks/components/
 * metricHelpContent.ts`'s own `profitTargetHelp` -- same registry-per-
 * feature convention this file's own top-of-file comment already
 * documents, not a cross-feature import.
 *
 * Unlike the stock-detail page's `profitTargetHelp` (`AnalysisResponse.
 * profit_target`, still gated on a fresh BUY signal), this one takes no
 * `signal` parameter at all: `RiskPosition.profit_target` (the field this
 * reads, `GET /api/portfolio/risk`) is computed for every open position
 * regardless of that ticker's current live signal -- see the
 * `backend-profit-target-open-position` task's `decisions` entry. A null
 * value here means only "neither target technique currently produces a
 * candidate for this position" (or the rarer column-validation degrade),
 * never "not a fresh BUY" -- there's no such gate to explain any more.
 */
/**
 * Help for the "Stop" figure shown by `PositionsTable.tsx`'s and
 * `RiskPanel.tsx`'s Stop column and `HeldPositionBanner.tsx`'s Stop field
 * (`frontend-trailing-stop-display`) -- all three now show
 * `RiskPosition.trailing_stop` (the hard-ratcheted trailing/profit-
 * protecting stop, Elder ch. 54, `app.portfolio.risk
 * .ratchet_trailing_profit_stop`) as the primary value, with the raw,
 * un-ratcheted `protective_stop` (SafeZone, docs/Analyse.md §7) demoted to
 * this popover's `valueInterpretation` rather than kept as its own
 * permanently-separate column/field -- see this task's `decisions` entry
 * for why: the two values are identical for most positions most of the time
 * (before a position's unrealized profit has crossed the breakeven-ratchet
 * trigger), so a second always-visible column would mostly just duplicate
 * the first one. `interpretValue` always states today's raw protective_stop
 * figure too, and explicitly says whether it currently differs from the
 * shown trailing stop (and in which direction) -- so the detail a trader
 * would want (the live, unratcheted number) is still one click away, not
 * silently dropped.
 */
export const stopHelp = {
  metricLabel: 'Stop',
  definition:
    'The stop currently protecting this position -- a hard ratchet that, once reported, never moves below any value this app has shown for it before (Elder ch. 54 "Don’t Let a Winning Trade Turn into a Loss" and its companion "Move Your Stop Only in the Direction of Your Trade"). Equal to the plain volatility-based protective stop (SafeZone concept, docs/Analyse.md §7) until this position’s unrealized profit crosses a 10%-of-entry-price trigger; from that point on it locks in at least breakeven and keeps protecting a growing share of the profit earned beyond that point.',
  elderContext:
    'Distinct from the raw protective stop alone: that figure is a pure point-in-time SafeZone recomputation and CAN move down day to day as volatility/the recent swing low change, even for a winning trade. This value never does once a position has started earning the ratchet’s protection -- it can be tighter (higher) or looser (lower) than today’s raw protective stop on any given day, since the two are independent stop-setting techniques meant to be considered together, not one superseding the other (docs/Analyse.md §7; app.portfolio.risk.ratchet_trailing_profit_stop’s own docstring).',
  interpretValue(trailingStop: number, protectiveStop: number): string {
    // A float-equality tolerance, not `===` -- `trailing_stop` is a running
    // max folded over daily closes server-side, so a pre-trigger position
    // (where the two values are defined to be identical) could in principle
    // differ from `protective_stop` by sub-cent floating-point noise alone.
    if (Math.abs(trailingStop - protectiveStop) < 0.005) {
      return `Currently ${trailingStop.toFixed(2)} -- equal to today’s raw protective stop, since this position’s profit hasn’t yet crossed the breakeven trigger that starts the ratchet protecting it.`
    }
    const direction =
      trailingStop > protectiveStop
        ? 'tighter (higher) than'
        : 'looser (lower) than'
    return `Currently ${trailingStop.toFixed(2)} -- ${direction} today’s raw protective stop (${protectiveStop.toFixed(2)}): the ratchet has already locked in a value from an earlier day that this position’s own current volatility-based recompute alone wouldn’t produce today.`
  },
}

export const profitTargetHelp = {
  metricLabel: 'Profit Target',
  definition: PROFIT_TARGET_DEFINITION,
  elderContext: `Paired with a sanity check Elder treats as close to a hard rule: potential reward should be at least 2x the risk to this same position’s protective stop shown alongside it ${PROFIT_TARGET_ELDER_CONTEXT_SUFFIX} A held position’s own profit target reflects what a FRESH entry at today’s price would target -- not a re-evaluation of the price this position was originally bought at.`,
  interpretValue(profitTarget: ProfitTargetOut | null): string {
    if (!profitTarget) {
      return 'Currently unavailable for this position -- neither technique (the channel/Tradebill formula or the nearest support/resistance zone above current price) currently produces a candidate, e.g. a young ticker with under ~100 weeks of weekly history and no yet-detected resistance zone above the current price.'
    }
    const sourceLabel =
      profitTarget.source === 'channel'
        ? 'the channel/Tradebill formula (current price + 30% of the weekly chart’s Autoenvelope/channel height)'
        : 'the nearest detected support/resistance zone above current price'
    const ratioClause =
      profitTarget.reward_risk_ratio == null
        ? 'The reward:risk ratio is undefined right now, since today’s close is already at or below the computed protective stop.'
        : `Reward:risk ratio ${profitTarget.reward_risk_ratio.toFixed(1)}:1 (potential reward ${profitTarget.distance_to_target.toFixed(2)}/share vs. risk ${profitTarget.distance_to_stop.toFixed(2)}/share to the protective stop).`
    const meetsClause = profitTarget.meets_minimum_reward_risk
      ? 'This clears Elder’s 2:1 minimum.'
      : 'This FAILS Elder’s 2:1 minimum -- he treats that as close to a hard no-trade rule, not just a caution.'
    return `Currently ${profitTarget.price.toFixed(2)}, from ${sourceLabel}. ${ratioClause} ${meetsClause}`
  },
}

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
