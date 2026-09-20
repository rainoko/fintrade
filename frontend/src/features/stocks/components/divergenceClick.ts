import type { MouseEventParams, SeriesMarkerBarPosition, Time } from 'lightweight-charts'
import type { DivergenceOut } from '../../../api/stocks'
import { timeToDateString } from '../../../utils/chart'

/**
 * `true` when a chart click's own `MouseEventParams.time` lands on one of
 * `divergence`'s two extreme dates -- the "clicked a divergence marker"
 * test both `PriceChart.tsx`'s and `OscillatorChart.tsx`'s
 * `chart.subscribeClick` handlers use (frontend-divergence-markers). The
 * one genuinely shared piece of divergence-click logic between the two
 * charts -- unlike each chart's own line/marker-building helpers (kept
 * local per component, same convention `buildOverlayData`/
 * `buildOscillatorSeriesData` already establish for conceptually-similar
 * but shape-specific series builders), the "did this click land on either
 * extreme date" test is identical regardless of which chart/pane it's
 * checked against, so it's colocated here rather than duplicated.
 *
 * Compares by date string (`timeToDateString`, `utils/chart.ts`) rather
 * than the raw `Time` value, since a clicked `Time` comes back as a
 * `BusinessDay` object even though this app always feeds the library a
 * plain `'YYYY-MM-DD'` string -- see that helper's own doc comment.
 */
export function clickedDivergenceExtreme(
  divergence: DivergenceOut,
  param: MouseEventParams<Time>,
): boolean {
  if (!param.time) {
    return false
  }
  const clickedDate = timeToDateString(param.time)
  return (
    clickedDate === divergence.first_extreme_date ||
    clickedDate === divergence.second_extreme_date
  )
}

/**
 * `true` when BOTH of `divergence`'s own extreme dates fall within
 * `[firstDate, lastDate]` -- the currently visible bar/point range
 * (inclusive) -- the gate `PriceChart.tsx`'s and `OscillatorChart.tsx`'s
 * own divergence-drawing effects both check before adding the connecting
 * `LineSeries`/markers/click subscription for a divergence.
 *
 * Post-review fix (PR #158, blocking finding): this task originally drew
 * the divergence overlay unconditionally, regardless of the chart's
 * currently selected range -- unlike `selectDisplayedZones`/
 * `buildFalseBreakoutMarkers` (PR #152), which already window to the
 * visible bar range for exactly this reason. Since this task only ever
 * draws the single latest divergence (which can legitimately be many
 * months old), an unwindowed 2-point `LineSeries` whose own points sit
 * outside the visible range routinely stretched Lightweight Charts' time
 * scale to cover the gap, squashing the actual candlestick/oscillator
 * content into an unreadable sliver (reproduced live: AAPL's real bearish
 * MACD-Histogram divergence at the default 1Y range, switching to 1M).
 *
 * Requires BOTH extremes in range, not just one overlapping -- a single
 * out-of-range point on either end of the 2-point line still distorts the
 * axis the same way a fully-out-of-range one does. Colocated here (like
 * `clickedDivergenceExtreme` above) since the "is this divergence
 * currently within the visible window" test is identical regardless of
 * which chart/pane it's checked against -- both the chart-drawing effects
 * and each chart's own legend (to decide what `divergenceHelp.interpretValue`
 * should say) share this one function rather than duplicating the
 * string-date-range comparison.
 *
 * Compared as plain `'YYYY-MM-DD'` strings (lexicographic order is date
 * order for this format) -- the same convention
 * `buildFalseBreakoutMarkers` (`PriceChart.tsx`) already uses for its own
 * `reentry_date` windowing check.
 */
export function isDivergenceInRange(
  divergence: DivergenceOut,
  firstDate: string,
  lastDate: string,
): boolean {
  return (
    divergence.first_extreme_date >= firstDate &&
    divergence.first_extreme_date <= lastDate &&
    divergence.second_extreme_date >= firstDate &&
    divergence.second_extreme_date <= lastDate
  )
}

/**
 * The marker `text`/`position` pair for a divergence overlay, shared between
 * `PriceChart.tsx`'s `buildDivergencePriceOverlay` (which marks the two
 * *price* swing points) and `OscillatorChart.tsx`'s
 * `buildDivergenceIndicatorOverlay` (which marks the two *indicator*
 * readings) -- both charts mark the exact same divergence at the exact same
 * two dates, so the label wording and up/down marker placement convention
 * must stay identical between them. Post-review fix (frontend-divergence-
 * markers-followups): previously copy-pasted verbatim in both files, which
 * the PR that added this overlay had already avoided for the one other
 * genuinely shared piece of divergence logic (`clickedDivergenceExtreme`
 * above) -- factored out here alongside it so a future change to the label
 * text or the up/down convention can't leave the two charts silently out of
 * sync.
 *
 * `position` is a `SeriesMarkerBarPosition` ('belowBar' for a bullish
 * divergence -- marking the swing LOW the divergence is built from --
 * 'aboveBar' for a bearish one, marking the swing HIGH), specifically NOT
 * the wider `SeriesMarkerPosition` union (which also includes a price-
 * relative position, requiring its own `price` field `SeriesMarker<Time>`
 * doesn't have for a bar-relative marker) -- both callers pass this
 * straight through to their own `SeriesMarker<Time>` objects.
 */
export function divergenceMarkerLabelAndPosition(divergence: DivergenceOut): {
  label: string
  position: SeriesMarkerBarPosition
} {
  return {
    label: divergence.kind === 'bullish' ? 'Bullish divergence' : 'Bearish divergence',
    position: divergence.kind === 'bullish' ? 'belowBar' : 'aboveBar',
  }
}
