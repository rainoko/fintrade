import type { HistoryResponse } from '../../../api/stocks'

/**
 * One bar's worth of shape this module actually needs -- just `date`/`high`/
 * `low` -- rather than the full `HistoryResponse['bars'][number]` (which also
 * carries `open`/`close`/`volume` this module never reads). Structurally
 * compatible with `HistoryResponse['bars'][number]` (an OHLCVBar always has
 * these three fields too), so `PriceChart.tsx` can pass its own already-
 * `hasFiniteOhlc`-filtered bars straight through with no extra mapping step.
 */
export type FibonacciBar = Pick<HistoryResponse['bars'][number], 'date' | 'high' | 'low'>

/**
 * Standard Fibonacci retracement ratios (research task, this task's own
 * checklist item 1 -- see this task's `decisions` entry for the full
 * research writeup): 0%/23.6%/38.2%/50%/61.8%/78.6%/100%, the exact set
 * TradingView's built-in "Fib Retracement"/"Auto Fib Retracement" tools (and
 * most other charting platforms) default to. 50% isn't itself a Fibonacci
 * ratio, but every mainstream charting tool includes it alongside the true
 * Fibonacci ratios (23.6% = a rounded Fibonacci-sequence ratio, 38.2%/61.8%
 * = the golden ratio and its complement, 78.6% = the square root of 61.8%) --
 * omitting it would be the one surprising deviation from convention, not a
 * simplification. Extension levels beyond 100% (127.2%, 161.8%, ...) are
 * deliberately NOT included -- this task's own title/description scope this
 * feature to *retracement* levels specifically, and adding extensions would
 * be new, unrequested scope beyond what a "retracement" tool conventionally
 * draws.
 */
export const FIBONACCI_RATIOS: readonly number[] = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]

/** Minimum number of currently-visible bars needed for a swing high/low to
 * mean anything -- mirrors the `finiteBars.length < 2` guard the existing
 * support/resistance zone effect (`PriceChart.tsx`) already uses for the
 * exact same "a single bar has no meaningful span" reason (this task's own
 * checklist item 5). */
export const MIN_BARS_FOR_FIBONACCI_SWING = 2

/**
 * `bars` filtered to only those whose `date` falls within
 * `[firstDate, lastDate]` inclusive -- the same `firstDate`/`lastDate`
 * windowing convention `selectVisibleIndicatorPoints`/`buildFalseBreakoutMarkers`/
 * `isDivergenceInRange`/`isKangarooTailInRange` already use for their own
 * overlays in `PriceChart.tsx`.
 */
export function selectVisibleBars<T extends { date: string }>(
  bars: readonly T[],
  firstDate: string,
  lastDate: string,
): T[] {
  return bars.filter((bar) => bar.date >= firstDate && bar.date <= lastDate)
}

/**
 * The two anchor points a Fibonacci retracement is drawn between -- the
 * highest `high` and lowest `low` among the bars passed in (see
 * `findFibonacciSwing`'s own doc comment for why this simple "extremes of
 * the visible range" rule was chosen over a more sophisticated swing-point/
 * pivot detector), plus the `direction` that determines which end gets the
 * 0% label (see `computeFibonacciLevels`).
 */
export interface FibonacciSwing {
  highPrice: number
  highDate: string
  lowPrice: number
  lowDate: string
  /**
   * `'up'` when the swing high is the more recent of the two extremes (an
   * uptrend still in progress, or one that just topped out -- the
   * retracement levels below the high are read as potential pullback/
   * support levels), `'down'` when the swing low is more recent (the mirror
   * image -- levels above the low are read as potential bounce/resistance
   * levels). Ties (the high and low bar share the same date -- e.g. exactly
   * one visible bar, or a rare same-day extreme) default to `'up'`, an
   * arbitrary but harmless tie-break since there's no real "which came
   * first" signal to read in that case.
   */
  direction: 'up' | 'down'
}

/**
 * Finds the swing high/low pair a Fibonacci retracement is drawn from, among
 * `bars` (expected to already be windowed to the chart's currently *visible*
 * range -- see `PriceChart.tsx`'s own Fibonacci-drawing effect, which passes
 * `selectVisibleBars`'s output here, not the full fetched history).
 *
 * Decision (this task's `decisions` entry, checklist item 1): the swing
 * high/low are simply the absolute highest `high` and lowest `low` among the
 * visible bars -- NOT a more sophisticated swing-point/pivot detector (e.g.
 * `backend-swing-point-detector`'s local-extrema algorithm, which this app
 * already has for a different purpose: support/resistance zone detection).
 * Research before picking (per this checklist item's own instruction):
 * TradingView's built-in "Auto Fib Retracement" study -- the closest
 * mainstream precedent for "Fibonacci levels calculated automatically from
 * the visible range, recalculated on pan/zoom", matching this task's own
 * framing almost exactly -- documents doing exactly this: "the indicator
 * automatically finds the most significant/extreme price swing visible on
 * the chart" by scanning the visible bars for their highest high and lowest
 * low, not by running a separate pivot/fractal detector first. The
 * alternative (reusing a pivot-point algorithm to pick two *local* extrema
 * instead of the two *global* ones) was considered and rejected: it would
 * need its own set of tunable parameters (lookback window, minimum swing
 * size) with no textual basis in this task's own description or
 * docs/Analyse.md for what those should be, whereas "highest high / lowest
 * low in view" has exactly one unambiguous answer for any given visible
 * range and matches this task's own literal wording ("calculated
 * automatically to current view").
 *
 * Returns `null` when there are fewer than `MIN_BARS_FOR_FIBONACCI_SWING`
 * bars, or when the highest high equals the lowest low (a perfectly flat
 * range -- every bar has the exact same high/low -- with no meaningful
 * spread to draw retracement levels across); both are this task's own
 * checklist item 5 degenerate cases.
 */
export function findFibonacciSwing(bars: readonly FibonacciBar[]): FibonacciSwing | null {
  if (bars.length < MIN_BARS_FOR_FIBONACCI_SWING) {
    return null
  }
  let highBar = bars[0]
  let lowBar = bars[0]
  for (const bar of bars) {
    // `>=`/`<=` (not strict `>`/`<`) so that when the extreme value recurs
    // across more than one bar, the *most recent* bar at that value wins --
    // matching the spirit of `FibonacciSwing.direction`'s own documented
    // same-date tie-break. A strict comparison would keep the first bar seen
    // at a tied extreme, which can flip the computed `direction` relative to
    // what "the more recent extreme gets 0%" is meant to produce (see this
    // task's `decisions` entry for the worked example).
    if (bar.high >= highBar.high) {
      highBar = bar
    }
    if (bar.low <= lowBar.low) {
      lowBar = bar
    }
  }
  if (highBar.high === lowBar.low) {
    return null
  }
  return {
    highPrice: highBar.high,
    highDate: highBar.date,
    lowPrice: lowBar.low,
    lowDate: lowBar.date,
    direction: lowBar.date <= highBar.date ? 'up' : 'down',
  }
}

export interface FibonacciLevel {
  ratio: number
  price: number
}

/**
 * Projects a `FibonacciSwing` into one price per `FIBONACCI_RATIOS` entry.
 *
 * For an `'up'` swing (high is the more recent extreme), 0% lands at the
 * high and 100% at the low -- `price = high - ratio * (high - low)` -- the
 * standard reading of the levels below the high as potential pullback/
 * support levels on the way back down toward the low. For a `'down'` swing
 * (low is more recent), the mirror image: 0% at the low, 100% at the high --
 * `price = low + ratio * (high - low)` -- levels above the low read as
 * potential bounce/resistance levels on the way back up toward the high.
 * This "most recent extreme = 0%, retrace back toward the older one" rule is
 * the same one TradingView's Auto Fib Retracement study uses to orient its
 * own levels (see `findFibonacciSwing`'s own doc comment for the research
 * this is grounded in).
 */
export function computeFibonacciLevels(swing: FibonacciSwing): FibonacciLevel[] {
  const { highPrice, lowPrice, direction } = swing
  const range = highPrice - lowPrice
  return FIBONACCI_RATIOS.map((ratio) => ({
    ratio,
    // Rounded to the nearest cent -- both to match every other price value
    // displayed in this app (two decimal places, e.g. `toFixed(2)`) and to
    // sidestep binary floating-point noise from the multiplication above
    // (e.g. `90 + 0.618 * 30` computes to `108.53999999999999`, not
    // `108.54`, in IEEE-754 double arithmetic) -- a plotted price line's
    // exact value should never depend on which of the two mathematically
    // equivalent formulas (`high - ratio*range` vs `low + ratio*range`)
    // happened to be used for a given direction.
    price: Math.round((direction === 'up' ? highPrice - ratio * range : lowPrice + ratio * range) * 100) / 100,
  }))
}

/**
 * `"23.6%"`/`"50%"`/`"100%"` -- a ratio's percentage label with the minimum
 * digits needed (no trailing `.0` for the whole-number ratios 0/50/100, one
 * decimal place for the rest), used as each price line's `title` on the
 * chart (`PriceChart.tsx`) and in `fibonacciHelp`'s explanation text
 * (`metricHelpContent.ts`).
 */
export function formatFibonacciRatioLabel(ratio: number): string {
  const percent = Math.round(ratio * 1000) / 10
  const label = Number.isInteger(percent) ? percent.toFixed(0) : percent.toFixed(1)
  return `${label}%`
}
