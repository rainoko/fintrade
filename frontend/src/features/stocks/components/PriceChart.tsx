import Box from '@mui/material/Box'
import Stack from '@mui/material/Stack'
import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'
import {
  AreaSeries,
  BaselineSeries,
  CandlestickSeries,
  createSeriesMarkers,
  LineSeries,
  LineStyle,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react'
import type {
  DivergenceOut,
  HistoryInterval,
  HistoryResponse,
  IndicatorHistoryPoint,
  KangarooTailOut,
  SupportResistanceZone,
} from '../../../api/stocks'
import { AnchoredInfoBalloon } from '../../../components/common/InfoBalloon/InfoBalloon'
import EmptyState from '../../../components/common/EmptyState/EmptyState'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import { useIndicatorHistory } from '../hooks/useIndicatorHistory'
import { useStockAnalysis } from '../hooks/useStockAnalysis'
import { useStockHistory } from '../hooks/useStockHistory'
import { bringSeriesToFront, createBaseChart, isFiniteNumber } from '../../../utils/chart'
import {
  clickedDivergenceExtreme,
  divergenceMarkerLabelAndPosition,
  isDivergenceInRange,
} from './divergenceClick'
import {
  channelHelp,
  divergenceHelp,
  falseBreakoutHelp,
  kangarooTailHelp,
  mostRecentFalseBreakoutZone,
  supportResistanceZoneHelp,
  tideRegionHelp,
  valueZoneHelp,
} from './metricHelpContent'

export interface PriceChartProps {
  ticker: string
  /**
   * Reports every range-preset change (see `RANGE_OPTIONS` above) so a
   * parent composing this component with a sibling chart can mirror the
   * current selection — see `StockCharts.tsx` (frontend-oscillator-chart),
   * which passes it straight into `OscillatorChart`'s own `range` prop so
   * both panes always plot the same window. Optional: existing callers
   * (and this component's own tests) that don't need to mirror the
   * selection elsewhere can omit it.
   */
  onRangeChange?: (range: string) => void
  /**
   * Reports every interval-toggle change (Daily/Weekly), same rationale as
   * `onRangeChange` above — `StockCharts.tsx` uses it to gate
   * `OscillatorChart` on `interval === 'daily'`, matching this component's
   * own overlay-gating rule (`/indicators` is daily-cadence only, see
   * `overlayEnabled` below).
   */
  onIntervalChange?: (interval: HistoryInterval) => void
}

// Preset windows mapped to the API's `<N>d|w|m|y|max` range grammar
// (docs/architecture/API.md#get-apistocksstickerhistory). Decision
// (frontend-stock-history-chart task): a fixed preset list rather than a
// free-text range input — the API's grammar is permissive (any `<N>` count),
// but the task calls for "a range selector" and a small, curated set of
// presets is both simpler to test exhaustively and matches how the rest of
// the app's controls work (ToggleButtonGroup, not free text).
const RANGE_OPTIONS: ReadonlyArray<{ label: string; value: string }> = [
  { label: '1M', value: '1m' },
  { label: '3M', value: '3m' },
  { label: '6M', value: '6m' },
  { label: '1Y', value: '1y' },
  { label: 'Max', value: 'max' },
]

// Exported so `StockCharts.tsx` can initialize its own mirrored range/
// interval state to the exact same defaults this component starts with,
// rather than duplicating the literal values (and risking the two drifting
// apart if one is ever changed without the other).
export const DEFAULT_RANGE = '1y'
export const DEFAULT_INTERVAL: HistoryInterval = 'daily'
const CHART_HEIGHT = 320

/**
 * `GET /api/stocks/{ticker}/history` legitimately returns `null` for
 * open/high/low/close on a still-forming (not yet closed) trading day's bar
 * whenever the query window reaches today — yfinance reports NaN OHLC for an
 * in-progress session, which Pydantic serializes as JSON `null` even though
 * `OHLCVBar`'s fields are typed as required non-nullable floats (a backend
 * contract mismatch worth separate attention, tracked as a review comment on
 * this task — not fixed here, since the chart needs to defend against a
 * malformed bar regardless of what the backend's declared schema promises).
 * The generated `OHLCVBar` type says `number`, but the runtime value can be
 * `null` (or, in principle, `NaN`/`Infinity`), so this checks at the value
 * level rather than trusting the type.
 */
function hasFiniteOhlc(bar: HistoryResponse['bars'][number]): boolean {
  return [bar.open, bar.high, bar.low, bar.close].every(
    (value): value is number => typeof value === 'number' && Number.isFinite(value),
  )
}

/** A single point from `/indicators`, projected into the series this
 * overlay plots — computed in one pass over `points` (see `buildOverlayData`
 * below) rather than a separate `.map()`/loop pass per series, per this
 * task's followups review comment.
 *
 * `channelUpper`/`channelLower` (frontend-channel-overlay) are shorter than
 * `ema13`/`ema26`/`markers` whenever any leading bar's `channel_upper`/
 * `channel_lower` is still `null` (the Autoenvelope's ~100-bar warm-up
 * window not yet full, see `IndicatorHistoryPoint`'s own doc comment) — that
 * bar is simply omitted from these two arrays (Lightweight Charts renders a
 * gap across a missing time point, same convention `OscillatorChart.tsx`
 * already uses for `stochastic_k`/`force_index_2ema`), not padded with a
 * placeholder value.
 *
 * `valueZoneTop`/`valueZoneBottom` are the *pointwise* max/min of
 * `ema13`/`ema26` at each bar (never a fixed "ema13 is always on top"
 * assumption) — see this task's `decisions` entry for why: EMA13 and EMA26
 * cross whenever the trend flips, so a naive "top = ema13, bottom = ema26"
 * pairing would invert during a downtrend. Always computed (both EMAs are
 * non-nullable), unlike the channel bounds above.
 */
interface OverlayData {
  ema13: { time: Time; value: number }[]
  ema26: { time: Time; value: number }[]
  channelUpper: { time: Time; value: number }[]
  channelLower: { time: Time; value: number }[]
  valueZoneTop: { time: Time; value: number }[]
  valueZoneBottom: { time: Time; value: number }[]
  markers: SeriesMarker<Time>[]
}

/**
 * Projects `/indicators` points into the EMA13/EMA26 + channel-band +
 * value-zone line/area data plus BUY/SELL transition markers, in a single
 * pass. The marker logic builds one marker per *transition* into a BUY or
 * SELL signal (i.e. the bar differs from the previous point, and the
 * previous point isn't undefined — so the very first point is treated as a
 * transition from "no signal" too), not one marker per bar carrying that
 * signal — Decision (see this component's own doc comment and this task's
 * `decisions` entry): marking every BUY/SELL bar in e.g. a multi-week BUY
 * run would bury the actually meaningful "Trigger fired" moments
 * (docs/Analyse.md §5) under a wall of identical arrows. HOLD never gets a
 * marker — there's no Elder-Ray/Trigger event to mark for it, only the
 * absence of one.
 */
function buildOverlayData(
  points: readonly IndicatorHistoryPoint[],
  colors: { buy: string; sell: string },
): OverlayData {
  const ema13: OverlayData['ema13'] = []
  const ema26: OverlayData['ema26'] = []
  const channelUpper: OverlayData['channelUpper'] = []
  const channelLower: OverlayData['channelLower'] = []
  const valueZoneTop: OverlayData['valueZoneTop'] = []
  const valueZoneBottom: OverlayData['valueZoneBottom'] = []
  const markers: SeriesMarker<Time>[] = []
  let previousSignal: IndicatorHistoryPoint['signal'] | undefined
  for (const point of points) {
    const time = point.date as Time
    ema13.push({ time, value: point.ema_13 })
    ema26.push({ time, value: point.ema_26 })
    valueZoneTop.push({ time, value: Math.max(point.ema_13, point.ema_26) })
    valueZoneBottom.push({ time, value: Math.min(point.ema_13, point.ema_26) })
    if (isFiniteNumber(point.channel_upper)) {
      channelUpper.push({ time, value: point.channel_upper })
    }
    if (isFiniteNumber(point.channel_lower)) {
      channelLower.push({ time, value: point.channel_lower })
    }
    if (point.signal !== 'HOLD' && point.signal !== previousSignal) {
      markers.push({
        time,
        position: point.signal === 'BUY' ? 'belowBar' : 'aboveBar',
        shape: point.signal === 'BUY' ? 'arrowUp' : 'arrowDown',
        color: point.signal === 'BUY' ? colors.buy : colors.sell,
        text: point.signal,
      })
    }
    previousSignal = point.signal
  }
  return {
    ema13,
    ema26,
    channelUpper,
    channelLower,
    valueZoneTop,
    valueZoneBottom,
    markers,
  }
}

// Tide (Screen 1) background shading (frontend-tide-region-chart-shading):
// a private, invisible price scale dedicated to the per-segment
// region-shading `AreaSeries` below (`buildTideRegionSegments`) -- see this
// task's `decisions` entry for why this was chosen over the alternative of
// an unbounded/huge data value on the chart's own real price scale plus
// `autoscaleInfoProvider` returning null. Giving the shading its own
// `priceScaleId` (configured `visible: false` with zero scale margins, so
// its [0, 1] range maps exactly onto the pane's own pixel top/bottom) means
// each segment's `AreaSeries` can plot a single constant value (1) and
// always fill the FULL vertical height of the pane -- entirely decoupled
// from wherever the candlesticks/EMA/channel/zone content currently sits on
// the real price scale, with zero risk of ever influencing (or being
// distorted by) that scale's own autoscale range, and no
// astronomically-large data value whose pixel mapping would depend on the
// real scale's current bounds.
const TIDE_REGION_PRICE_SCALE_ID = 'tide-region-shading'

// Fill opacity (alpha, as a hex byte): deliberately much fainter than the
// value-zone (`33`, ~20%) or support/resistance zone (7%-29%, scaled by
// strength) shadings -- both of those cover only a slice of the visible
// price range, but this shading covers the ENTIRE pane behind every candle,
// EMA line, and other overlay on the chart, so it has to stay unobtrusive
// enough not to wash out everything drawn on top of it. Reused identically
// for the on-chart fill and the legend swatches below (same convention the
// value-zone/support-resistance legends already follow -- the swatch color
// should look like what's actually on the chart, not just a stand-in).
const TIDE_REGION_FILL_ALPHA = '14' // ~8%

/**
 * `points` filtered to only those whose `date` falls within
 * `[firstDate, lastDate]` inclusive -- the currently visible bar range, same
 * `firstDate`/`lastDate` windowing convention `buildFalseBreakoutMarkers`/
 * `isDivergenceInRange`/`isKangarooTailInRange` already use for their own
 * overlays (see those functions' own doc comments for the axis-distortion
 * class of bug this pattern exists to avoid, PR #152/#158). Unlike those
 * overlays (sourced from `/analysis`, a different query than the
 * candlesticks), `/indicators` is already fetched with the exact same
 * `range` param as `/history` (see `indicatorsQuery` in this component), so
 * this filter is a defensive belt-and-suspenders guard against the two
 * queries' bar sets not lining up exactly (e.g. a holiday/weekend
 * discrepancy, or one query's response landing mid-refetch) rather than a
 * correction for a structural mismatch the way the `/analysis`-sourced
 * overlays' windowing is.
 *
 * Exported so the chart-drawing effect (`buildTideRegionSegments`'s caller)
 * and the legend's `tideRegionHelp.interpretValue` call both read from the exact
 * same windowed dataset -- the same "one shared selection so two
 * computations can't drift" pattern `selectDisplayedZones`/
 * `mostRecentFalseBreakoutZone` already establish, per this task's own
 * context note on the PR #152 round-2 data-source-mismatch bug.
 */
function selectVisibleIndicatorPoints(
  points: readonly IndicatorHistoryPoint[],
  firstDate: string,
  lastDate: string,
): IndicatorHistoryPoint[] {
  return points.filter((point) => point.date >= firstDate && point.date <= lastDate)
}

interface TideRegionSegment {
  trend: IndicatorHistoryPoint['tide']['trend']
  /** Every bar in this contiguous stretch at a constant `value: 1` (see
   * `TIDE_REGION_PRICE_SCALE_ID`'s own comment for why the value itself is
   * an arbitrary constant on a dedicated [0, 1] scale), PLUS one trailing
   * point at the NEXT segment's own first date (still `value: 1`) when a
   * next segment exists -- see `buildTideRegionSegments`'s own doc comment
   * for why. */
  data: { time: Time; value: number }[]
}

/**
 * Projects already-windowed (`selectVisibleIndicatorPoints`) `/indicators`
 * points into one segment per contiguous run of bars sharing the same
 * `tide.trend` -- e.g. 20 Bullish bars, then 5 Bearish, then 40 Neutral
 * becomes 3 segments, not one array per trend. Each segment becomes its
 * OWN `AreaSeries` (see the caller in the chart-drawing effect below), the
 * same "one series per bounded, self-contained span" technique
 * `buildZoneRenderData` already established for support/resistance zone
 * bands, rather than three long-lived series (one per trend) spanning the
 * whole visible range.
 *
 * Decision (this task's `decisions` entry, superseding an earlier, WRONG
 * attempt at the "one series per trend" shape): `AreaSeries` does NOT
 * respect an omitted or even an explicit `WhitespaceData` point as a gap
 * for its FILL (only, per a live Lightweight Charts test page built to
 * confirm this precisely, for its line STROKE) -- it draws one continuous
 * fill bridging straight across from a series' own first real point to its
 * own last one, ignoring any gap in between. A "one array per trend" shape
 * therefore doesn't render three disjoint sets of rectangles at all; it
 * renders three giant overlapping blobs, each spanning from that trend's
 * FIRST occurrence in the visible range to its LAST, with whichever
 * trend's series happened to be added most recently painting over the
 * other two wherever they overlap -- exactly the bug a live browser
 * walkthrough against real ORCL/V Tide history caught (mocked unit tests
 * never exercised more than one gap, so never caught it). One series per
 * CONTIGUOUS segment sidesteps the question entirely: a segment's own data
 * never has a gap in it by construction, so there's nothing for the fill
 * to bridge across incorrectly.
 *
 * Each segment's data is extended with one extra point at the START of the
 * NEXT segment (same `value: 1`) -- without this, a single-bar segment
 * (a real, common case: Elder's Tide can flip for just a day or two) would
 * be a 1-point series, which `AreaSeries` renders as nothing at all (no
 * line/fill without a second point to draw between). Extending each
 * segment right up to the next one's own start makes even a 1-bar segment
 * a real 2-point span with actual width, and means every segment's shaded
 * region butts up exactly against the next one's, with no visible seam or
 * gap between them.
 *
 * Post-review fix (PR #169 needs_work): this forward-extension pass, by
 * construction, only ever gives segments 0..length-2 a trailing boundary --
 * the LAST segment has no "next" segment to extend toward, so a solo
 * single-bar final segment (the most recent visible bar's `tide.trend`
 * differing from the bar before it -- exactly the kind of brief flip this
 * comment already calls "a real, common case") was left as a 1-point
 * series, silently rendering NO shading for today's (rightmost, most
 * decision-relevant) background even though `tideRegionHelp.interpretValue`
 * kept describing a color for it. Fixed with a second, backward pass run
 * ONLY over however many segments at the tail still have fewer than 2
 * points after the forward pass (structurally, that can only ever be a run
 * starting at the very last segment -- the forward pass already guarantees
 * every other segment >= 2 points): for each such segment, reclaim the
 * boundary point the forward pass gave its own predecessor (pop the
 * predecessor's trailing extension back off, which is always safe -- the
 * forward pass guarantees that predecessor has >= 2 points to start with,
 * so popping one leaves it with at least its own real point) and prepend
 * the predecessor's own true last real point instead, so the two segments
 * meet at that shared boundary rather than the last segment's own single
 * date being reused as a zero-width duplicate. This cascades backward
 * exactly as far as needed to reach a segment with real width to spare --
 * see this task's `decisions` entry for the one (deliberately unhandled)
 * pathological case this can't fix: EVERY visible bar alternating trend
 * with its neighbor, leaving no segment with spare width to cascade from,
 * which Tide (driven by the weekly Impulse System color -- weekly EMA(13)
 * direction + weekly MACD-Histogram direction together, not their daily
 * equivalents) realistically never does.
 */
function buildTideRegionSegments(
  points: readonly IndicatorHistoryPoint[],
): TideRegionSegment[] {
  const segments: TideRegionSegment[] = []
  for (const point of points) {
    const time = point.date as Time
    const trend = point.tide.trend
    const current = segments.at(-1)
    if (current && current.trend === trend) {
      current.data.push({ time, value: 1 })
    } else {
      segments.push({ trend, data: [{ time, value: 1 }] })
    }
  }
  for (let i = 0; i < segments.length - 1; i++) {
    const nextSegmentStart = segments[i + 1].data[0]
    segments[i].data.push({ time: nextSegmentStart.time, value: 1 })
  }
  for (let i = segments.length - 1; i > 0 && segments[i].data.length < 2; i--) {
    const previous = segments[i - 1]
    previous.data.pop()
    // `previous.data.at(-1)` can never be `undefined` here -- structurally
    // unreachable, not merely assumed safe (post-review follow-up,
    // frontend-tide-region-chart-shading-followups, confirmed by fuzz-
    // testing every 2-symbol trend sequence up to length 10 in the PR #169
    // re-review). `previous` (`segments[i - 1]`) can only ever be popped
    // from ONCE across this whole backward loop, always before it could
    // later become an unshift TARGET (`segments[i]`) in an earlier
    // iteration -- and the forward-extension pass above already guarantees
    // every segment except the very last one has >= 2 points before this
    // loop starts, so popping one off `previous` here always leaves at
    // least its own one real point behind.
    const previousOwnLast = previous.data.at(-1) as (typeof previous.data)[number]
    segments[i].data.unshift({ time: previousOwnLast.time, value: 1 })
  }
  return segments
}

// Support/resistance zone display (frontend-support-resistance-overlay):
// `AnalysisResponse.support_resistance_zones` is already capped to the 15
// strongest zones by `strength_score` on the backend (see the field's own
// doc comment in api/types.ts), but even 15 translucent horizontal bands
// stacked on this chart's 320px-tall pane would be unreadable clutter -- a
// handful of the very strongest is what a trader would actually look for at
// a glance. Zones arrive already sorted strongest-first, so capping (after
// the relevance filter below) is just `.slice(0, MAX_DISPLAYED_ZONES)`.
// Decision (this task's `decisions` entry): a second, frontend-side cap
// distinct from the backend's own API-payload cap, since the two caps solve
// different problems (payload size vs. on-screen legibility).
const MAX_DISPLAYED_ZONES = 6

// Post-review fix (PR #152, blocking finding #1): a zone's `upper`/`lower`
// is whatever raw split-adjusted price level the backend detected, which for
// a ticker with a multi-decade history can sit an order of magnitude away
// from where the stock trades today (e.g. a pre-split-era level). Naively
// drawing the "6 strongest" zones regardless of how far they sit from the
// current price handed Lightweight Charts' default price-scale autoscale a
// `BaselineSeries` data point far outside the candlesticks' own range,
// stretching the y-axis until the actual OHLC/EMA/channel/marker content
// was squashed into an unreadable sliver -- reproduced across
// AAPL/NVDA/MSFT/AMD by the PR reviewer. Decision (this task's `decisions`
// entry): only a zone whose `[lower, upper]` band overlaps a window within
// `ZONE_RELEVANCE_PRICE_RATIO` (50%) of the most recent visible close is
// eligible to be drawn at all -- applied *before* the strongest-6 cap above,
// so a far-away zone can never occupy one of the 6 display slots and can
// never distort the axis, no matter how high its `strength_score`.
const ZONE_RELEVANCE_PRICE_RATIO = 0.5

// Follow-up fix (frontend-support-resistance-overlay-followups, checklist
// item 2): the fixed 50% price-ratio window above is anchored only to the
// latest visible close, not to the currently-visible bars' own price span --
// pr-reviewer's retry-round-1 stress test found this still let a zone ~40%
// above the latest close (inside the 50% window) distort a 1-month preset
// view's y-axis, squashing the actual candlestick/EMA/channel content into
// roughly 11% of the pane, even though the same zone against a 1-year view
// (naturally more price spread to absorb it) was fine. `isZoneRelevant`
// below now ALSO intersects the ratio window with a second window built
// from the actually-visible bars' own high/low span (`visibleBarPriceSpan`)
// -- `ZONE_RELEVANCE_VISIBLE_SPAN_MULTIPLE` times that span either side of
// the visible high/low. Intersecting (not replacing) the ratio window means
// this can only ever SHRINK the eligible window versus before, never widen
// it -- so the worst case is no worse than the ratio-only bound already
// reasoned through in PR #152's own `decisions` entry, while a narrow
// visible range (small own price span) now gets a correspondingly tighter
// window instead of always defaulting to the full 50%.
//
// `ZONE_RELEVANCE_MIN_VISIBLE_SPAN_RATIO` floors the span used in that
// multiple at 10% of `referencePrice` -- without it, a visible range that
// happens to be nearly flat (a quiet trading window, or this file's own
// 2-bar test fixtures) would collapse the span window to almost nothing,
// excluding zones that are still clearly relevant to where price actually
// sits. Decision (this task's `decisions` entry): chose intersecting with a
// floored multiple of the visible span (rather than e.g. replacing the
// ratio window outright, or a fixed absolute-dollar margin) since it only
// ever tightens the existing, already-reasoned-through ratio bound, and the
// floor keeps behavior for a normal-volatility view close to before while
// still bounding the narrow-range distortion case the review reproduced --
// `ZONE_RELEVANCE_VISIBLE_SPAN_MULTIPLE=2`/`ZONE_RELEVANCE_MIN_VISIBLE_SPAN_RATIO=0.1`
// were picked so every zone fixture already exercised by this file's own
// tests (all within the existing 2-bar fixtures' ~1.4%-of-price span) still
// passes unchanged, while a zone ~40% away against a realistically narrow
// (non-floor-dominated) visible span is excluded -- verified with a
// throwaway Playwright screenshot against the running app (not committed),
// not just unit tests.
const ZONE_RELEVANCE_VISIBLE_SPAN_MULTIPLE = 2
const ZONE_RELEVANCE_MIN_VISIBLE_SPAN_RATIO = 0.1

/** The actually-visible bars' own price span -- the min `low` and max `high`
 * across every currently visible bar (not just the first/last, since a
 * mid-range spike/dip is still part of what's actually on screen), used by
 * `isZoneRelevant`'s span-based window above. */
function visibleBarPriceSpan(
  bars: readonly { high: number; low: number }[],
): { low: number; high: number } {
  let low = Infinity
  let high = -Infinity
  for (const bar of bars) {
    if (bar.low < low) {
      low = bar.low
    }
    if (bar.high > high) {
      high = bar.high
    }
  }
  return { low, high }
}

/**
 * True when `zone`'s `[lower, upper]` band overlaps the window formed by
 * intersecting two windows: `referencePrice * (1 -/+ ZONE_RELEVANCE_PRICE_RATIO)`
 * (the original 50%-either-way price-ratio window), and `visibleSpan`'s own
 * `[low, high]` expanded by `ZONE_RELEVANCE_VISIBLE_SPAN_MULTIPLE` times its
 * own (floored) height either way -- see the constants' own comments above
 * for why both windows exist and are intersected rather than either alone.
 */
function isZoneRelevant(
  zone: SupportResistanceZone,
  referencePrice: number,
  visibleSpan: { low: number; high: number },
): boolean {
  const ratioWindowMin = referencePrice * (1 - ZONE_RELEVANCE_PRICE_RATIO)
  const ratioWindowMax = referencePrice * (1 + ZONE_RELEVANCE_PRICE_RATIO)
  const effectiveSpan = Math.max(
    visibleSpan.high - visibleSpan.low,
    referencePrice * ZONE_RELEVANCE_MIN_VISIBLE_SPAN_RATIO,
  )
  const spanWindowMin = visibleSpan.low - ZONE_RELEVANCE_VISIBLE_SPAN_MULTIPLE * effectiveSpan
  const spanWindowMax = visibleSpan.high + ZONE_RELEVANCE_VISIBLE_SPAN_MULTIPLE * effectiveSpan
  const windowMin = Math.max(ratioWindowMin, spanWindowMin)
  const windowMax = Math.min(ratioWindowMax, spanWindowMax)
  return zone.upper >= windowMin && zone.lower <= windowMax
}

/**
 * Zones actually eligible to be drawn on the chart: filtered to ones
 * relevant to `referencePrice`/`visibleSpan` (see `isZoneRelevant`), THEN
 * capped to the strongest `MAX_DISPLAYED_ZONES` (zones arrive already
 * sorted strongest-first, so this is a plain `.slice`) -- in that order, so
 * the relevance filter always runs before the cap and a distant zone can
 * never consume one of the 6 display slots. Shared by both
 * `buildZoneRenderData` (the shaded bands) and `buildFalseBreakoutMarkers`
 * (their false-breakout markers/stop lines) so the two stay in lockstep: a
 * false breakout is only ever marked for a zone whose band is actually
 * drawn.
 */
function selectDisplayedZones(
  zones: readonly SupportResistanceZone[],
  referencePrice: number,
  visibleSpan: { low: number; high: number },
): SupportResistanceZone[] {
  return zones
    .filter((zone) => isZoneRelevant(zone, referencePrice, visibleSpan))
    .slice(0, MAX_DISPLAYED_ZONES)
}

// Fill opacity (alpha, as a hex byte) for a zone's shaded band, scaled by
// its `strength_score` (0-100) -- this is how "visual weight reflecting
// strength" (this task's own description) is implemented: a weak/minor zone
// barely tints the chart, a major/long-lived one reads as clearly more
// prominent. The range is deliberately narrow enough that even the
// strongest zone's fill stays translucent -- candlesticks are always
// repainted on top of it (see `bringSeriesToFront` below), but a fully
// opaque fill would still make the tinting itself look like it's occluding
// the candle underneath, defeating the point of shading a *band* rather
// than drawing a solid rectangle.
const ZONE_MIN_FILL_ALPHA = 0x12 // ~7%
const ZONE_MAX_FILL_ALPHA = 0x4a // ~29%

function zoneFillAlphaHex(strengthScore: number): string {
  const clamped = Math.min(100, Math.max(0, strengthScore))
  const alpha = Math.round(
    ZONE_MIN_FILL_ALPHA + ((ZONE_MAX_FILL_ALPHA - ZONE_MIN_FILL_ALPHA) * clamped) / 100,
  )
  return alpha.toString(16).padStart(2, '0')
}

interface ZoneRenderData {
  zone: SupportResistanceZone
  /** Two points spanning the whole visible bar range at a constant `upper`
   * value -- the flat line a `BaselineSeries` plots, with `zone.lower` as
   * its `baseValue`. Unlike `AreaSeries` (which only fills from its line
   * down to the *bottom of the pane* -- see the value-zone comment below),
   * `BaselineSeries` fills only between its plotted line and its fixed
   * `baseValue` price, so a single series renders a self-contained,
   * precisely-bounded band with no opaque masking series needed at all --
   * see this task's `decisions` entry for why this was chosen over
   * reusing the value-zone's two-`AreaSeries` fill/mask technique. */
  data: { time: Time; value: number }[]
  fillColor: string
  lineColor: string
  lineStyle: LineStyle
}

/**
 * Projects already-selected (see `selectDisplayedZones` -- relevance-
 * filtered and strongest-6-capped) support/resistance zones into the
 * `BaselineSeries` render data this component plots. A zone's shading always
 * spans the *whole* currently-visible bar range (`firstTime`..`lastTime`),
 * not just the span between its own `first_touch_date`/`last_touch_date` --
 * a support/resistance level is still a live reference price today
 * regardless of when it originally formed, the standard technical-analysis
 * convention for drawing a horizontal S/R line across a whole chart.
 *
 * Color is support (`colors.support`) vs. resistance (`colors.resistance`)
 * by the zone's *current* `role` -- which already reflects a role flip after
 * a confirmed break (see `SupportResistanceZone.role`'s own doc comment) --
 * so a flipped zone is colored by what it means *now*, not what it meant
 * when it first formed. A flipped (`broken: true`) zone is additionally
 * drawn dashed rather than solid, the visual distinction this task's own
 * checklist calls for between a zone that's flipped role and one that
 * hasn't.
 */
function buildZoneRenderData(
  zones: readonly SupportResistanceZone[],
  firstTime: Time,
  lastTime: Time,
  colors: { support: string; resistance: string },
): ZoneRenderData[] {
  return zones.map((zone) => {
    const baseColor = zone.role === 'support' ? colors.support : colors.resistance
    return {
      zone,
      data: [
        { time: firstTime, value: zone.upper },
        { time: lastTime, value: zone.upper },
      ],
      fillColor: `${baseColor}${zoneFillAlphaHex(zone.strength_score)}`,
      lineColor: baseColor,
      lineStyle: zone.broken ? LineStyle.Dashed : LineStyle.Solid,
    }
  })
}

/**
 * `true` when `breakout.reentry_date` falls within `[firstDate, lastDate]`
 * -- the currently visible bar range (inclusive) -- the same windowing test
 * `isDivergenceInRange`/`isKangarooTailInRange` already apply to their own
 * overlays, for the exact same reason (see `isKangarooTailInRange`'s own
 * doc comment). Shared by `buildFalseBreakoutMarkers` below (which windows
 * every zone's marker/price-line) and the legend's own `falseBreakoutHelp`
 * `inVisibleRange` computation (this task's follow-up fix) so the two can
 * never disagree about whether a given episode is actually on screen.
 */
function isFalseBreakoutInRange(
  breakout: SupportResistanceZone['false_breakout'],
  firstDate: string,
  lastDate: string,
): breakout is NonNullable<SupportResistanceZone['false_breakout']> {
  return breakout != null && breakout.reentry_date >= firstDate && breakout.reentry_date <= lastDate
}

/**
 * One marker per already-selected (see `selectDisplayedZones`) zone's most
 * recent false-breakout episode (Elder ch. 18: "a specific, high-value trade
 * setup", not noise -- see `falseBreakoutHelp` in metricHelpContent.ts)
 * whose `reentry_date` falls within the currently visible bar range
 * (`firstDate`..`lastDate`) -- omitted, not erroring, when it falls outside
 * the current range/window selection, since the zone's own shaded band
 * still renders regardless (see `buildZoneRenderData` above); only this
 * specific historical marker is windowed to what Lightweight Charts can
 * actually plot a point at.
 *
 * Positioned/shaped on the side the failed move actually reached: `aboveBar`
 * with a downward arrow for an `'up'` false breakout (price broke above,
 * failed, and is now expected to reverse back down), the mirror image for
 * `'down'` -- the arrow direction is the *reversal* a false breakout
 * signals, not the direction of the failed move itself.
 */
function buildFalseBreakoutMarkers(
  zones: readonly SupportResistanceZone[],
  firstDate: string,
  lastDate: string,
  color: string,
): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = []
  for (const zone of zones) {
    const breakout = zone.false_breakout
    if (!isFalseBreakoutInRange(breakout, firstDate, lastDate)) {
      continue
    }
    markers.push({
      time: breakout.reentry_date as Time,
      position: breakout.direction === 'up' ? 'aboveBar' : 'belowBar',
      shape: breakout.direction === 'up' ? 'arrowDown' : 'arrowUp',
      color,
      text: 'False breakout',
    })
  }
  return markers.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0))
}

interface DivergencePriceOverlay {
  /** Two points spanning `first_extreme_date`..`second_extreme_date` at
   * `first_extreme_price`/`second_extreme_price` -- the connecting line a
   * `LineSeries` plots between the two compared price swing points. */
  line: { time: Time; value: number }[]
  markers: SeriesMarker<Time>[]
}

/**
 * Projects the single currently-qualifying divergence
 * (`AnalysisResponse.divergence`) into a 2-point connecting line plus a
 * marker at each of its two compared price swing points --
 * `first_extreme_price`/`second_extreme_price`, at
 * `first_extreme_date`/`second_extreme_date`. Decision (this task's
 * `decisions` entry): only the single latest divergence is drawn, not a
 * reconstructed history of every past divergence from `/indicators`'
 * per-bar `divergence` field -- that field repeats the same divergence
 * across every bar it's still the most-recently-confirmed one for, so
 * turning it into distinct historical events would need its own
 * de-duplication pass with no clear textual basis for how, and the
 * checklist's own "which two extremes are being compared... for THIS
 * ticker" phrasing already reads as "the current one", singular, matching
 * `AnalysisResponse.divergence`'s own singular shape.
 *
 * Distinct from the BUY/SELL transition markers (`buildOverlayData` above)
 * on both axes the task calls for: `circle` shape (not `arrowUp`/
 * `arrowDown`) and `theme.palette.divergence.main` (not `signal.buy`/
 * `signal.sell`) -- see `theme.ts`'s own comment for why that color was
 * added rather than reusing an existing one.
 */
function buildDivergencePriceOverlay(
  divergence: DivergenceOut,
  color: string,
): DivergencePriceOverlay {
  const { label, position } = divergenceMarkerLabelAndPosition(divergence)
  return {
    line: [
      {
        time: divergence.first_extreme_date as Time,
        value: divergence.first_extreme_price,
      },
      {
        time: divergence.second_extreme_date as Time,
        value: divergence.second_extreme_price,
      },
    ],
    markers: [
      { time: divergence.first_extreme_date as Time, position, shape: 'circle', color, text: label },
      { time: divergence.second_extreme_date as Time, position, shape: 'circle', color, text: label },
    ],
  }
}

/**
 * `true` when `tail.tail_date` falls within `[firstDate, lastDate]` -- the
 * currently visible bar range (inclusive) -- the same windowing test
 * `isDivergenceInRange` (`divergenceClick.ts`) already applies to the
 * divergence overlay, for the exact same reason: a marker/price-line at a
 * date outside the currently selected range has nothing sensible to plot
 * against (see that function's own doc comment for the axis-distortion bug
 * this pattern was introduced to fix, PR #152/#158). Only one date to check
 * here (unlike divergence's two extremes), since a Kangaroo Tail is a
 * single-bar event.
 */
function isKangarooTailInRange(
  tail: KangarooTailOut,
  firstDate: string,
  lastDate: string,
): boolean {
  return tail.tail_date >= firstDate && tail.tail_date <= lastDate
}

/**
 * Projects `AnalysisResponse.kangaroo_tail` into a single chart marker at
 * the tail bar itself (frontend-kangaroo-tail-markers) -- `square` shape
 * (unused by every other marker type on this chart: BUY/SELL use
 * `arrowUp`/`arrowDown`, divergence uses `circle`, false breakouts use
 * `arrowDown`/`arrowUp`) in `theme.palette.kangarooTail.main`, so this
 * reads as visually distinct from all of them at a glance, per this task's
 * own "distinct from every other marker type already present" requirement.
 *
 * Positioned on the side the tail itself physically points to -- `aboveBar`
 * for an `'up'` (bearish) tail, which spiked to a new HIGH, `belowBar` for
 * a `'down'` (bullish) one, which spiked to a new LOW -- mirroring where
 * the tall bar's own tip actually sits, the same "position mirrors the
 * event's own direction" convention `buildFalseBreakoutMarkers` already
 * uses for its arrow shape (though that one marks the *reversal* side, not
 * the event's own side -- this marker sits right at the pattern itself, so
 * it belongs on the same side the tail protrudes toward).
 */
function buildKangarooTailMarker(tail: KangarooTailOut, color: string): SeriesMarker<Time> {
  const label = tail.direction === 'up' ? 'Kangaroo Tail (bearish)' : 'Kangaroo Tail (bullish)'
  return {
    time: tail.tail_date as Time,
    position: tail.direction === 'up' ? 'aboveBar' : 'belowBar',
    shape: 'square',
    color,
    text: label,
  }
}

/**
 * Candlestick price chart for `GET /api/stocks/{ticker}/history`, built on
 * TradingView Lightweight Charts. Owns its own range/interval selection as
 * local UI state (Frontend.md §2 — not server data, so plain `useState`
 * rather than lifted into the page or a shared store) and feeds it straight
 * into `useStockHistory`, which keys its query by both params so a change
 * always triggers a real refetch (see useStockHistory.ts).
 *
 * Also overlays `GET /api/stocks/{ticker}/indicators` (via
 * `useIndicatorHistory`) on top of the candlesticks: EMA13/EMA26 as native
 * Lightweight Charts line series -- drawn here for the value-zone shading
 * (the band between them) and because EMA(26) feeds daily MACD, not because
 * they drive Screen 1/Tide, which is the weekly Impulse System color
 * (weekly EMA(13) direction + weekly MACD-Histogram direction together, per
 * docs/Analyse.md §2/§3/§4) rather than this daily EMA13/EMA26 pair -- plus
 * BUY/SELL markers via the series-markers plugin at each bar where the
 * signal actually changed (see
 * `buildOverlayData` above) — see this task's (frontend-chart-signal-
 * overlay) `decisions` entry for why this combination was chosen over a
 * background-band treatment, and why the overlay is daily-only. No
 * indicator/signal math happens here — every plotted value comes straight
 * from the backend response, per Frontend.md §5's "backend computes,
 * frontend displays" rule. `IndicatorsPanel` (fed by `/analysis`) remains
 * the latest-value-only counterpart shown alongside this chart.
 *
 * Also draws the Autoenvelope/channel bands (`channel_upper`/`channel_lower`
 * — backend-channel-envelope-exposure) as two dashed line series, plus a
 * shaded "value zone" between EMA13/EMA26 (frontend-channel-overlay) — see
 * this task's `decisions` entry for the two-`AreaSeries`-mask technique used
 * to fill only the zone *between* the two EMAs (not down to the bottom of
 * the pane, which is all a single `AreaSeries` can do natively), and for why
 * the channel bands are two plain dashed lines rather than a second shaded
 * region (avoiding two overlapping shaded zones cluttering the same chart).
 * A `common/MetricHelp` affordance next to the range/interval controls
 * explains both (`channelHelp`/`valueZoneHelp`, `metricHelpContent.ts`),
 * following this app's established explanatory pattern.
 *
 * Also draws `GET /api/stocks/{ticker}/analysis`'s `support_resistance_zones`
 * (via its own `useStockAnalysis(ticker)` call, deduped by TanStack Query
 * against `StockDetailPage`'s own use of the same query key — same
 * self-contained-per-chart-component pattern `useIndicatorHistory` already
 * uses between this component and `OscillatorChart`) as horizontal shaded
 * `BaselineSeries` bands, one per zone, colored support/resistance and
 * weighted (fill opacity) by `strength_score` (frontend-support-resistance-
 * overlay) — see `buildZoneRenderData`'s own doc comment for why a
 * `BaselineSeries` (bounded fill between its line and a fixed `baseValue`)
 * was chosen over reusing the value-zone's two-`AreaSeries` mask technique,
 * and this task's `decisions` entry for the display cap and color/dash
 * choices. Independent of the EMA/channel/marker overlay above (not gated on
 * `overlayEnabled`/daily-only — a price level is interval-agnostic, unlike a
 * daily-cadence EMA series). A zone's most recent false-breakout episode
 * (Elder ch. 18, "a specific, high-value trade setup") gets its own marker
 * plus a dashed `createPriceLine` at the failed move's own extreme — the
 * book's explicit stop-placement reference. `supportResistanceZoneHelp`/
 * `falseBreakoutHelp` (`metricHelpContent.ts`) explain both via the same
 * `common/MetricHelp` legend-row pattern as the channel/value-zone pair
 * above.
 *
 * Still owns its own range/interval `ToggleButtonGroup` controls and local
 * `useState` for them (unchanged from before), but now also reports every
 * change via the optional `onRangeChange`/`onIntervalChange` props so a
 * parent can mirror the current selection into a sibling pane —
 * `StockCharts.tsx` (frontend-oscillator-chart) is the one real consumer of
 * this today, keeping `OscillatorChart`'s Stochastic/Force Index/MACD
 * Histogram panes on the exact same range and daily-only gating as this
 * chart's own overlay. See this task's `decisions` entry for why a
 * mirrored-callback pattern was used instead of converting this component
 * into a fully controlled one.
 *
 * Also draws `GET /api/stocks/{ticker}/analysis`'s `kangaroo_tail`
 * (frontend-kangaroo-tail-markers) — the single most recently confirmed
 * Kangaroo Tail reversal pattern (Elder ch. 20, "fingers") — as a `square`
 * marker at the tail bar itself, distinct in both shape and color
 * (`theme.palette.kangarooTail.main`) from the BUY/SELL/divergence/false-
 * breakout markers already on this chart, plus a dashed price line at
 * `suggested_stop` (the book's own "halfway through the tail" reference,
 * same treatment as the false-breakout stop line above). Windowed to the
 * currently visible bar range via `isKangarooTailInRange` — same
 * axis-distortion-avoidance pattern `isDivergenceInRange` already
 * established for the divergence overlay (see this task's `decisions`
 * entry). Since the pattern's underlying "unusual bar" shape isn't obvious
 * from a name alone, `kangarooTailHelp`'s `MetricHelp` legend affordance
 * explains it using this tail's own actual numbers (its range vs. the
 * recent average, its open/close relative to the extreme it spiked to,
 * the suggested stop) rather than a generic definition — see
 * `metricHelpContent.ts`'s own doc comment on `kangarooTailHelp`.
 *
 * Also shades the whole pane's background per historical Tide (Screen 1)
 * state (frontend-tide-region-chart-shading) — green/red/amber behind the
 * candlesticks for every bar `/indicators`' now-per-bar `tide.trend` field
 * (backend-indicator-history-tide-exposure) reports Bullish/Bearish/Neutral,
 * so it's visually obvious when BUY/SELL were even structurally possible
 * (Screen 1 gates both before Screen 2/3 ever run) vs. gated off entirely by
 * a Neutral or opposite-direction Tide — the very first idea logged in
 * docs/ideas.md. One `AreaSeries` per CONTIGUOUS same-trend segment (see
 * `buildTideRegionSegments` — not one long-lived series per trend, which
 * would render three overlapping blobs instead of the actual disjoint
 * history; see that function's own doc comment and this task's `decisions`
 * entry) on their own dedicated, invisible `[0, 1]` price scale — see
 * `TIDE_REGION_PRICE_SCALE_ID`'s own comment for why that technique was
 * chosen over an `autoscaleInfoProvider`-excluded huge-value `AreaSeries` on
 * the chart's real price scale. `tideRegionHelp`'s `MetricHelp` legend affordance
 * explains the shading and reports what fraction of the currently visible
 * bars were each trend, computed from the exact same windowed points the
 * shading itself draws from (`selectVisibleIndicatorPoints`).
 */
export default function PriceChart({
  ticker,
  onRangeChange,
  onIntervalChange,
}: PriceChartProps) {
  const theme = useTheme()
  const [range, setRange] = useState<string>(DEFAULT_RANGE)
  const [interval, setInterval] = useState<HistoryInterval>(DEFAULT_INTERVAL)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  // Divergence-marker click-to-explain (frontend-divergence-markers): page
  // coordinates of the last divergence-marker click, or `null` before any
  // click / once the balloon is closed -- fed into `AnchoredInfoBalloon`
  // below, since a canvas-drawn marker has no DOM trigger element of its
  // own for `InfoBalloon`'s usual internal anchorEl state.
  const [divergenceBalloonAnchor, setDivergenceBalloonAnchor] = useState<{
    top: number
    left: number
  } | null>(null)

  const historyQuery = useStockHistory(ticker, { range, interval })
  // Exclude any bar with a null/non-finite OHLC value (a still-forming
  // latest trading day — see hasFiniteOhlc above) rather than passing it to
  // Lightweight Charts, which throws synchronously on a non-numeric value
  // and would otherwise crash the whole page, not just this chart.
  const bars = (historyQuery.data?.bars ?? []).filter(hasFiniteOhlc)
  const hasBars = bars.length > 0

  // `/indicators` only computes daily-cadence values (no `interval` param —
  // see API.md), so plotting its EMA13/EMA26/signal points against a
  // *weekly*-interval candlestick series would misalign the two entirely
  // (a daily EMA line drawn over weekly bars is neither a daily nor a
  // weekly chart). Decision (this task's `decisions` entry): only fetch and
  // render the overlay while `interval === 'daily'`, rather than requesting
  // it unconditionally and silently mis-plotting it against weekly bars.
  const overlayEnabled = interval === 'daily'
  const indicatorsQuery = useIndicatorHistory(
    ticker,
    { range },
    { enabled: overlayEnabled },
  )

  // Support/resistance zones (frontend-support-resistance-overlay): a
  // separate query from `/analysis`, deduped by TanStack Query against
  // `StockDetailPage`'s own `useStockAnalysis(ticker)` call for the same
  // ticker (same query key, same cache entry). Not gated on
  // `overlayEnabled` — see this component's own doc comment above for why
  // zones render regardless of daily/weekly interval.
  const analysisQuery = useStockAnalysis(ticker)

  // Create the chart once a container is mounted and there are bars to
  // plot, and tear it down whenever the underlying data changes (a new
  // range/interval, or the same query refetching) — Lightweight Charts has
  // no built-in "replace the series data and keep going" story that's
  // simpler than just recreating the chart, and a fresh chart per dataset
  // avoids ever showing stale candles from a previous ticker/range while
  // the current query is loading (the container itself isn't rendered in
  // that case — see the `hasBars` check in the JSX below). Depends on
  // `historyQuery.data` itself (a new object per response) rather than the
  // `bars` array derived from it, since the derived array is a fresh
  // reference on every render regardless of whether the data changed.
  useEffect(() => {
    const container = containerRef.current
    const data = historyQuery.data
    if (!container || !data) {
      return
    }
    // Recompute rather than close over the `bars` above: this effect only
    // depends on `historyQuery.data` (see below), so it must derive
    // everything it needs from `data` directly rather than from a value
    // computed in a possibly-stale render.
    const finiteBars = data.bars.filter(hasFiniteOhlc)
    if (finiteBars.length === 0) {
      return
    }

    const chart = createBaseChart(container)
    const series = chart.addSeries(CandlestickSeries)
    series.setData(
      finiteBars.map((bar) => ({
        time: bar.date,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      })),
    )
    chart.timeScale().fitContent()

    chartRef.current = chart
    seriesRef.current = series

    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [historyQuery.data])

  // Adds the EMA13/EMA26 line series + BUY/SELL signal markers onto the
  // *existing* chart/candlestick series created by the effect above, rather
  // than recreating the whole chart — this effect's own deps
  // (`indicatorsQuery.data`, `overlayEnabled`) change independently of
  // `historyQuery.data` (the indicator fetch resolves separately, often
  // slightly later, than the OHLCV fetch), so re-running just this effect
  // swaps the overlay series in place without a jarring full-chart
  // teardown/recreate.
  //
  // Also depends on `historyQuery.data` so that when the effect above *does*
  // recreate the chart (new range/interval), this effect's own overlay gets
  // torn down and rebuilt against the new chart too. When both effects fire
  // on the same dependency change, React runs sibling effects' CLEANUP
  // functions in DECLARATION order, not reversed (verified against React's
  // actual behavior — a previous version of this comment had this backwards
  // and shipped a crash: see this task's decisions entry) — so the
  // candlestick effect's cleanup (declared first, above) always finishes
  // running `chart.remove()` and nulling `chartRef`/`seriesRef` *before*
  // this effect's cleanup runs. By the time this cleanup executes, `chart`
  // may therefore already be a disposed `ChartApi` — calling
  // `chart.removeSeries(...)` on it throws synchronously (Lightweight
  // Charts' `ensureDefined`), which is exactly the reported crash. The guard
  // below checks the refs still point at *this* chart/series before
  // touching them; if the candlestick effect already tore it down, there's
  // nothing left to clean up here.
  useEffect(() => {
    const chart = chartRef.current
    const series = seriesRef.current
    if (!chart || !series || !overlayEnabled) {
      return
    }
    const points = indicatorsQuery.data?.points ?? []
    if (points.length === 0) {
      return
    }

    const {
      ema13,
      ema26,
      channelUpper,
      channelLower,
      valueZoneTop,
      valueZoneBottom,
      markers,
    } = buildOverlayData(points, {
      buy: theme.palette.signal.buy,
      sell: theme.palette.signal.sell,
    })

    // Value-zone shading: two `AreaSeries` in a "fill, then mask" pair,
    // since Lightweight Charts has no native "fill the region between two
    // arbitrary line series" primitive (only fill-from-a-line-to-the-
    // bottom-of-the-pane, or a custom series plugin -- overkill for this):
    // `zoneTopSeries` paints a translucent fill from `valueZoneTop` (the
    // pointwise-higher of EMA13/EMA26 at each bar) down to the bottom of the
    // visible range, then `zoneBottomMaskSeries` repaints everything from
    // `valueZoneBottom` down in the *chart's own opaque background color*,
    // erasing the portion below the lower EMA and leaving only the true
    // "value zone" between the two visibly shaded. This depends on the
    // chart's `layout.background` actually being opaque white
    // (`theme.palette.background.paper`, matching `createBaseChart`'s
    // transparent layer showing this page's plain white background through
    // it) -- see this task's `decisions` entry for why that assumption is
    // safe today (this app has no dark-mode/alternate-theme support at all)
    // but would need revisiting if one were ever added.
    //
    // Bug fixed post-review (PR #151): Lightweight Charts draws later-added
    // series above earlier ones on the same pane, and both zone series used
    // to be added *after* the candlestick series (created in the effect
    // above). That put the opaque `zoneBottomMaskSeries` on top of the
    // candlesticks, painting over (hiding) any wick/body that fell below the
    // zone's bottom boundary -- routine whenever price trades below the
    // fast/slow EMA (any pullback or downtrend), not an edge case. Fixed by
    // explicitly reordering `series` (the candlestick series) via
    // `bringSeriesToFront` once these two zone series are both added, below
    // (not by relying on creation order alone, which is what caused the
    // bug): candlesticks are always drawn after -- i.e. on top of -- the
    // zone fill/mask, regardless of how many overlay series exist or the
    // order this effect happens to add them in.
    const zoneTopSeries = chart.addSeries(AreaSeries, {
      topColor: `${theme.palette.info.main}33`,
      bottomColor: `${theme.palette.info.main}33`,
      lineVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      title: 'Value Zone',
    })
    zoneTopSeries.setData(valueZoneTop)

    const zoneBottomMaskSeries = chart.addSeries(AreaSeries, {
      topColor: theme.palette.background.paper,
      bottomColor: theme.palette.background.paper,
      lineVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    zoneBottomMaskSeries.setData(valueZoneBottom)

    // Move the candlestick series to the very end of this pane's render-
    // order stack (dynamically -- see `bringSeriesToFront`'s own doc
    // comment) so it always paints on top of the zone fill/mask, and of any
    // other fill series another effect on this same pane may have added
    // (the support/resistance zone bands below) -- see the block comment
    // above.
    bringSeriesToFront(chart, series)

    const ema13Series = chart.addSeries(LineSeries, {
      color: theme.palette.primary.main,
      lineWidth: 1,
      title: 'EMA 13',
      priceLineVisible: false,
      lastValueVisible: false,
    })
    ema13Series.setData(ema13)

    const ema26Series = chart.addSeries(LineSeries, {
      color: theme.palette.secondary.main,
      lineWidth: 1,
      title: 'EMA 26',
      priceLineVisible: false,
      lastValueVisible: false,
    })
    ema26Series.setData(ema26)

    // Channel/Autoenvelope bands: two dashed lines (not a second shaded
    // region -- see this component's own doc comment) in a color distinct
    // from both EMAs and the value-zone fill. Data may be shorter than
    // `ema13`/`ema26` (the ~100-bar warm-up window, see `buildOverlayData`);
    // Lightweight Charts renders a gap across the missing leading span
    // rather than erroring.
    const channelUpperSeries = chart.addSeries(LineSeries, {
      color: theme.palette.info.main,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      title: 'Channel Upper',
      priceLineVisible: false,
      lastValueVisible: false,
    })
    channelUpperSeries.setData(channelUpper)

    const channelLowerSeries = chart.addSeries(LineSeries, {
      color: theme.palette.info.main,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      title: 'Channel Lower',
      priceLineVisible: false,
      lastValueVisible: false,
    })
    channelLowerSeries.setData(channelLower)

    const markersPlugin = createSeriesMarkers(series, markers)

    return () => {
      // See the block comment above: skip if the candlestick effect's
      // cleanup already disposed this chart/series (refs no longer match).
      if (chartRef.current !== chart || seriesRef.current !== series) {
        return
      }
      chart.removeSeries(zoneTopSeries)
      chart.removeSeries(zoneBottomMaskSeries)
      chart.removeSeries(ema13Series)
      chart.removeSeries(ema26Series)
      chart.removeSeries(channelUpperSeries)
      chart.removeSeries(channelLowerSeries)
      markersPlugin.detach()
    }
  }, [historyQuery.data, indicatorsQuery.data, overlayEnabled, theme])

  // Tide (Screen 1) background shading (frontend-tide-region-chart-shading):
  // adds one `AreaSeries` per contiguous same-trend segment (see
  // `buildTideRegionSegments`) onto the *existing* chart/candlestick series,
  // on their own dedicated invisible price scale (`TIDE_REGION_PRICE_SCALE_ID`)
  // so they always fill the pane's full vertical height regardless of where
  // price/EMA/channel content sits on the real scale. A SEPARATE effect from
  // the signal-overlay one above (same "deliberately separate, differently-
  // gated effects on the same chart" convention this component already
  // uses) even though the gating conditions are identical
  // (`overlayEnabled`, `indicatorsQuery.data`) -- isolating this from the
  // signal-overlay effect's own large, carefully-ordered cleanup keeps
  // neither effect's correctness dependent on the other's internals (see
  // this task's `decisions` entry).
  useEffect(() => {
    const chart = chartRef.current
    const series = seriesRef.current
    const data = historyQuery.data
    if (!chart || !series || !overlayEnabled || !data) {
      return
    }
    const finiteBars = data.bars.filter(hasFiniteOhlc)
    if (finiteBars.length === 0) {
      return
    }
    const points = indicatorsQuery.data?.points ?? []
    if (points.length === 0) {
      return
    }
    const firstDate = finiteBars[0].date
    const lastDate = finiteBars[finiteBars.length - 1].date
    const visiblePoints = selectVisibleIndicatorPoints(points, firstDate, lastDate)
    if (visiblePoints.length === 0) {
      return
    }

    const segments = buildTideRegionSegments(visiblePoints)
    const colorByTrend: Record<IndicatorHistoryPoint['tide']['trend'], string> = {
      BULLISH: theme.palette.signal.buy,
      BEARISH: theme.palette.signal.sell,
      NEUTRAL: theme.palette.signal.hold,
    }

    const regionSeriesList = segments.map((segment) => {
      const color = colorByTrend[segment.trend]
      const regionSeries = chart.addSeries(AreaSeries, {
        priceScaleId: TIDE_REGION_PRICE_SCALE_ID,
        topColor: `${color}${TIDE_REGION_FILL_ALPHA}`,
        bottomColor: `${color}${TIDE_REGION_FILL_ALPHA}`,
        // Also fixes the "last value" label's own badge color (which
        // defaults to Lightweight Charts' own green `lineColor` default,
        // '#33D778', regardless of `topColor`/`bottomColor` -- a real bug
        // a live browser walkthrough caught: every region series' label
        // badge rendered identically green, not its own trend color, since
        // `lineColor` had never been set explicitly). Deliberately still
        // set even though `lineVisible: false` hides the stroke itself,
        // purely for this fallback.
        lineColor: color,
        lineVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        // No `title`: naming these series would put a "Tide: Bullish"-
        // style label badge in the chart's top-right corner even with
        // `lastValueVisible: false` (Lightweight Charts renders a title
        // label "next to" the last-value label independently of whether
        // that label itself is shown -- another live-walkthrough finding,
        // see this task's `decisions` entry) -- pure clutter for a
        // decorative background band with no real numeric "last value" to
        // label. The legend row + MetricHelp below the chart is this
        // overlay's sole explanation surface, not an inline axis label.
        //
        // Fixes this series' own price range to exactly [0, 1] regardless
        // of its (arbitrary, constant) data values -- redundant with the
        // price scale's own zero margins set below, but a second, explicit
        // guard against this series ever contributing to (or being
        // affected by) autoscale, matching the belt-and-suspenders posture
        // every other overlay on this chart already takes against
        // autoscale distortion (see this task's `decisions` entry).
        autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 1 } }),
      })
      regionSeries.setData(segment.data)
      return regionSeries
    })

    // Configure the dedicated price scale once per effect run (on whichever
    // segment series happens to be first -- every segment shares the same
    // `priceScaleId`, so any one of them can configure it): invisible (no
    // axis labels/lines of its own -- this is purely an internal coordinate
    // system, never a real price the user should read off an axis) and
    // zero scale margins, so its [0, 1] range maps exactly onto the pane's
    // own pixel top/bottom with no padding gap left unshaded. Deliberately
    // called AFTER the `addSeries` calls above, not before: Lightweight
    // Charts only registers a custom `priceScaleId` once a series actually
    // references it -- calling `chart.priceScale(id)` for an ID nothing has
    // used yet throws synchronously ("Trying to apply price scale options
    // with incorrect ID"), a real integration bug this task's own mocked
    // unit tests couldn't catch (the mock has no such validation) but a
    // live browser walkthrough against real cached ORCL/V data did -- see
    // this task's `decisions` entry. Guarded on `regionSeriesList.length`
    // (rather than assuming at least one segment always exists) since
    // `visiblePoints.length > 0` is already checked above, so this is only
    // ever empty in a state this effect can't otherwise reach -- but an
    // empty `visiblePoints.length === 0` check earlier doesn't, by itself,
    // logically guarantee `segments` is non-empty to a type checker.
    regionSeriesList[0]?.priceScale().applyOptions({
      visible: false,
      scaleMargins: { top: 0, bottom: 0 },
    })

    // Keep the candlestick series painting on top of this new background
    // shading too (see `bringSeriesToFront`'s own doc comment) -- these
    // series sit on their own price scale, but z-order within a pane is
    // independent of price scale, so this still applies unchanged.
    bringSeriesToFront(chart, series)

    return () => {
      // See the signal-overlay effect's own cleanup guard above: skip if
      // the candlestick effect already disposed this chart/series.
      if (chartRef.current !== chart || seriesRef.current !== series) {
        return
      }
      regionSeriesList.forEach((regionSeries) => chart.removeSeries(regionSeries))
    }
  }, [historyQuery.data, indicatorsQuery.data, overlayEnabled, theme])

  // Support/resistance zones (frontend-support-resistance-overlay): adds
  // the horizontal `BaselineSeries` bands, false-breakout markers, and
  // false-breakout stop price lines onto the *existing* chart/candlestick
  // series, same "add onto the existing chart" pattern as the signal-
  // overlay effect above. Deliberately a SEPARATE effect (not folded into
  // the one above) since its own gating differs: it depends on
  // `analysisQuery.data`, not `indicatorsQuery.data`, and it is NOT gated
  // on `overlayEnabled` (daily-only) -- a support/resistance price level
  // applies regardless of which interval the candlesticks themselves are
  // plotted at, unlike the EMA/channel overlay above (see this component's
  // own doc comment).
  useEffect(() => {
    const chart = chartRef.current
    const series = seriesRef.current
    const data = historyQuery.data
    if (!chart || !series || !data) {
      return
    }
    const finiteBars = data.bars.filter(hasFiniteOhlc)
    // Post-review fix (PR #152, blocking finding #2): `buildZoneRenderData`
    // plots each zone as a 2-point `BaselineSeries` spanning
    // `firstDate`..`lastDate`. With exactly one visible bar, those two
    // points collapse to an identical timestamp, and Lightweight Charts'
    // `setData` asserts strictly-ascending time and throws synchronously on
    // a duplicate -- an uncaught crash via `AppErrorBoundary`. Skipping the
    // whole zone overlay (not just the offending band) whenever fewer than
    // two bars are visible is the simplest safe behavior: a single visible
    // candle has no meaningful "span" for a horizontal zone band to cover
    // anyway.
    if (finiteBars.length < 2) {
      return
    }
    const zones = analysisQuery.data?.support_resistance_zones ?? []
    if (zones.length === 0) {
      return
    }

    const firstDate = finiteBars[0].date
    const lastDate = finiteBars[finiteBars.length - 1].date
    // Reference price for the relevance filter (see `isZoneRelevant`): the
    // most recent visible bar's close -- effectively "today's price" for
    // any range that includes the present (every preset does), so a zone
    // far from it (e.g. a pre-split-era level) never gets a display slot.
    const referencePrice = finiteBars[finiteBars.length - 1].close
    const displayedZones = selectDisplayedZones(
      zones,
      referencePrice,
      visibleBarPriceSpan(finiteBars),
    )
    if (displayedZones.length === 0) {
      return
    }
    const zoneRenderData = buildZoneRenderData(
      displayedZones,
      firstDate as Time,
      lastDate as Time,
      {
        support: theme.palette.signal.buy,
        resistance: theme.palette.signal.sell,
      },
    )

    const zoneSeriesList = zoneRenderData.map(
      ({ zone, data: bandData, fillColor, lineColor, lineStyle }) => {
        // `BaselineSeries` fills only between its plotted line (`upper`,
        // constant across `bandData`) and its fixed `baseValue` price
        // (`zone.lower`) -- see `ZoneRenderData`'s own doc comment for why
        // this needs no opaque masking series the way the value-zone shading
        // above does. `bottomFillColor*`/`bottomLineColor` (the colors used
        // if the line ever dipped *below* `baseValue`) are irrelevant here --
        // `zone.upper > zone.lower` always (the backend never emits a
        // zero/negative-height zone), so only the "top" fill/line ever
        // renders -- but they're still set (matching the same translucent
        // color) rather than left at the library's own green/red defaults,
        // in case that invariant is ever violated by a future backend change.
        const zoneSeries = chart.addSeries(BaselineSeries, {
          baseValue: { type: 'price', price: zone.lower },
          topFillColor1: fillColor,
          topFillColor2: fillColor,
          bottomFillColor1: fillColor,
          bottomFillColor2: fillColor,
          topLineColor: lineColor,
          bottomLineColor: lineColor,
          lineWidth: 1,
          lineStyle,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          title: `${zone.role === 'support' ? 'Support' : 'Resistance'} zone`,
        })
        zoneSeries.setData(bandData)
        return zoneSeries
      },
    )

    const falseBreakoutMarkers = buildFalseBreakoutMarkers(
      displayedZones,
      firstDate,
      lastDate,
      theme.palette.warning.main,
    )
    const falseBreakoutMarkersPlugin =
      falseBreakoutMarkers.length > 0
        ? createSeriesMarkers(series, falseBreakoutMarkers)
        : null

    // A dashed horizontal price line at each windowed false breakout's own
    // `extreme_price` -- Elder's explicit stop-placement reference ("place
    // a stop near this extreme, not further out"). Only for zones whose
    // false breakout also has a marker (same `firstDate`/`lastDate`
    // windowing) so a price line never appears for an episode with no
    // corresponding visible marker.
    const falseBreakoutPriceLines: IPriceLine[] = []
    for (const { zone } of zoneRenderData) {
      const breakout = zone.false_breakout
      if (!isFalseBreakoutInRange(breakout, firstDate, lastDate)) {
        continue
      }
      falseBreakoutPriceLines.push(
        series.createPriceLine({
          price: breakout.extreme_price,
          color: theme.palette.warning.main,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: 'False-breakout stop',
        }),
      )
    }

    // Keep the candlestick series painting on top of every fill series in
    // this pane -- both these zone bands and the value-zone AreaSeries pair
    // from the effect above, whichever effect happens to run/re-run last
    // (see `bringSeriesToFront`'s own doc comment for why a dynamic call is
    // required once two independent effects both add fill series here).
    bringSeriesToFront(chart, series)

    return () => {
      // See the signal-overlay effect's own cleanup guard above: skip if
      // the candlestick effect already disposed this chart/series.
      if (chartRef.current !== chart || seriesRef.current !== series) {
        return
      }
      zoneSeriesList.forEach((zoneSeries) => chart.removeSeries(zoneSeries))
      falseBreakoutPriceLines.forEach((priceLine) => series.removePriceLine(priceLine))
      falseBreakoutMarkersPlugin?.detach()
    }
  }, [historyQuery.data, analysisQuery.data, theme])

  // Divergence overlay (frontend-divergence-markers): the single currently-
  // qualifying divergence (`AnalysisResponse.divergence`, or nothing when
  // `null`) drawn as a connecting `LineSeries` plus a `circle` marker at
  // each of its two compared price swing points -- see
  // `buildDivergencePriceOverlay`'s own doc comment for why only the
  // latest one, not a reconstructed history, is drawn, and for why its
  // shape/color are deliberately distinct from the BUY/SELL transition
  // markers above. A SEPARATE effect from the support/resistance one above
  // (same "deliberately separate, differently-gated effects on the same
  // chart" convention this component already uses) even though both read
  // `analysisQuery.data`, since this one additionally wires
  // `chart.subscribeClick` to open the click-to-explain balloon --
  // isolating that subscription's own lifecycle from the zone-band effect's
  // keeps each effect's cleanup simple and independently reasoned-about.
  //
  // Post-review fix (PR #158, blocking finding): windowed to the currently
  // visible bar range (`finiteBars[0].date`..`finiteBars.at(-1).date`),
  // same pattern `selectDisplayedZones`/`buildFalseBreakoutMarkers` already
  // established (PR #152) for the exact same failure class -- see
  // `isDivergenceInRange`'s own doc comment (divergenceClick.ts) for why an
  // unwindowed divergence line distorted the whole chart's time scale
  // whenever its own (often much older) dates fell outside the selected
  // range. Unlike the zone bands, there's no "still draw it, just capped"
  // fallback here: a 2-point line with even one point outside the visible
  // range has nothing sensible to render, so the whole overlay (line,
  // markers, click subscription) is simply skipped for this render -- the
  // legend below still surfaces the divergence via `divergenceHelp`'s own
  // `inVisibleRange` clause (see this task's `decisions` entry for why the
  // legend stays visible rather than also hiding).
  useEffect(() => {
    const chart = chartRef.current
    const series = seriesRef.current
    const data = historyQuery.data
    if (!chart || !series || !data) {
      return
    }
    const divergence = analysisQuery.data?.divergence
    if (!divergence) {
      return
    }
    // No separate "finiteBars.length === 0" guard needed here (unlike the
    // candlestick/zone effects above, which both check it): `chart`/`series`
    // (checked above) are only ever non-null when the candlestick effect's
    // OWN `finiteBars.length === 0` guard passed for this exact
    // `historyQuery.data` -- and per this component's own documented
    // effect-cleanup-ordering invariant (see the signal-overlay effect's
    // comment above), every sibling effect's cleanup for a data change runs
    // to completion (nulling these refs) before any effect's new body runs,
    // so `finiteBars` is guaranteed non-empty whenever this line is reached.
    const finiteBars = data.bars.filter(hasFiniteOhlc)
    const firstDate = finiteBars[0].date
    const lastDate = finiteBars[finiteBars.length - 1].date
    if (!isDivergenceInRange(divergence, firstDate, lastDate)) {
      return
    }

    const color = theme.palette.divergence.main
    const { line, markers } = buildDivergencePriceOverlay(divergence, color)

    const divergenceLineSeries = chart.addSeries(LineSeries, {
      color,
      lineWidth: 2,
      lineStyle: LineStyle.LargeDashed,
      title: 'Divergence',
      priceLineVisible: false,
      lastValueVisible: false,
    })
    divergenceLineSeries.setData(line)
    const divergenceMarkersPlugin = createSeriesMarkers(series, markers)

    // Keep the candlestick series painting on top of this new line series
    // too, same defensive call every other series-adding effect on this
    // pane ends with (see `bringSeriesToFront`'s own doc comment).
    bringSeriesToFront(chart, series)

    // Click-to-explain: Lightweight Charts' series-marker plugin has no DOM
    // element of its own for `InfoBalloon`'s usual `ButtonBase`/`onClick`
    // trigger pattern to attach to, so this opens `AnchoredInfoBalloon`
    // (common/InfoBalloon.tsx) at the click's own page coordinates instead
    // -- see that component's own doc comment for why a coordinate-anchored
    // variant exists at all. `param.sourceEvent?.pageX/pageY` (not
    // `param.point`, which is pane-relative canvas pixels, not page
    // coordinates a `Popover`'s `anchorPosition` needs) -- see
    // `clickedDivergenceExtreme`'s own doc comment for the date-matching
    // logic.
    // An arrow function assigned to a `const`, not a `function` declaration
    // -- TypeScript doesn't carry the `if (!divergence) return` narrowing
    // above into a hoisted function declaration (it conservatively assumes
    // one could theoretically run before the narrowing check), but does for
    // a `const`-bound closure defined after it.
    const handleClick = (param: MouseEventParams<Time>) => {
      if (!clickedDivergenceExtreme(divergence, param)) {
        return
      }
      const pageX = param.sourceEvent?.pageX
      const pageY = param.sourceEvent?.pageY
      if (pageX == null || pageY == null) {
        return
      }
      setDivergenceBalloonAnchor({ top: pageY, left: pageX })
    }
    chart.subscribeClick(handleClick)

    return () => {
      // See the signal-overlay effect's own cleanup guard above: skip if
      // the candlestick effect already disposed this chart/series.
      if (chartRef.current !== chart || seriesRef.current !== series) {
        return
      }
      chart.unsubscribeClick(handleClick)
      chart.removeSeries(divergenceLineSeries)
      divergenceMarkersPlugin.detach()
    }
  }, [historyQuery.data, analysisQuery.data, theme])

  // Kangaroo Tail overlay (frontend-kangaroo-tail-markers): the single most
  // recently confirmed Kangaroo Tail (`AnalysisResponse.kangaroo_tail`, or
  // nothing when `null`) drawn as one `square` marker at the tail bar
  // itself plus a dashed price line at `suggested_stop` -- see
  // `buildKangarooTailMarker`'s own doc comment for why the shape/color are
  // deliberately distinct from every other marker on this chart. A
  // SEPARATE effect from the divergence one above (same "deliberately
  // separate, differently-gated effects on the same chart" convention this
  // component already uses for the zone-band/divergence pair), even though
  // both read `analysisQuery.data`, since this one has no click-to-explain
  // subscription to isolate the lifecycle of the way the divergence effect
  // does.
  //
  // Windowed to the currently visible bar range via `isKangarooTailInRange`
  // -- same axis-distortion-avoidance pattern PR #152/#158 already
  // established for zone false-breakout markers/the divergence overlay (see
  // this task's `decisions` entry): a single out-of-range marker/price line
  // has nothing sensible to plot, and an out-of-range price line specifically
  // would still render at its own price level even with no visible bar at
  // its date, which is confusing rather than merely absent.
  useEffect(() => {
    const chart = chartRef.current
    const series = seriesRef.current
    const data = historyQuery.data
    if (!chart || !series || !data) {
      return
    }
    const kangarooTail = analysisQuery.data?.kangaroo_tail
    if (!kangarooTail) {
      return
    }
    // Same "no separate finiteBars.length === 0 guard needed" reasoning as
    // the divergence effect above -- see its own comment for the
    // effect-cleanup-ordering invariant this relies on.
    const finiteBars = data.bars.filter(hasFiniteOhlc)
    const firstDate = finiteBars[0].date
    const lastDate = finiteBars[finiteBars.length - 1].date
    if (!isKangarooTailInRange(kangarooTail, firstDate, lastDate)) {
      return
    }

    const color = theme.palette.kangarooTail.main
    const marker = buildKangarooTailMarker(kangarooTail, color)
    const kangarooTailMarkersPlugin = createSeriesMarkers(series, [marker])

    const kangarooTailStopLine = series.createPriceLine({
      price: kangarooTail.suggested_stop,
      color,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'Kangaroo Tail stop',
    })

    bringSeriesToFront(chart, series)

    return () => {
      // See the signal-overlay effect's own cleanup guard above: skip if
      // the candlestick effect already disposed this chart/series.
      if (chartRef.current !== chart || seriesRef.current !== series) {
        return
      }
      kangarooTailMarkersPlugin.detach()
      series.removePriceLine(kangarooTailStopLine)
    }
  }, [historyQuery.data, analysisQuery.data, theme])

  function handleRangeChange(_event: ReactMouseEvent<HTMLElement>, value: string | null) {
    if (value !== null) {
      setRange(value)
      onRangeChange?.(value)
    }
  }

  function handleIntervalChange(
    _event: ReactMouseEvent<HTMLElement>,
    value: HistoryInterval | null,
  ) {
    if (value !== null) {
      setInterval(value)
      onIntervalChange?.(value)
    }
  }

  // Shared gate for the signal-overlay states below: the underlying
  // candlestick chart must already have something to overlay onto
  // (`historyQuery.isSuccess && hasBars`), and the overlay must be
  // applicable at all (`overlayEnabled` — daily interval only, see above).
  // Computed once rather than repeated across each overlay state's own JSX
  // guard.
  const showOverlaySection = historyQuery.isSuccess && hasBars && overlayEnabled

  // Latest daily close (from `/history`, not `/indicators` — `channelHelp`'s
  // interpretation reads where *price* currently sits relative to the
  // channel bounds) and the latest `/indicators` point (channel bounds +
  // EMA13/EMA26 themselves), used by the legend's `MetricHelp` affordances
  // below. Both are `undefined` until their own query resolves — `MetricHelp`
  // /`channelHelp`/`valueZoneHelp` all already treat a missing value as "not
  // yet available" rather than throwing (same nullable-value convention as
  // every other `metricHelpContent.ts` entry).
  const latestClose = bars.at(-1)?.close
  const latestIndicatorPoint = indicatorsQuery.data?.points.at(-1)

  // Tide (Screen 1) background-shading legend data (frontend-tide-region-
  // chart-shading): runs the exact same `selectVisibleIndicatorPoints`
  // window the tide-shading effect above uses (`bars` here is already
  // `historyQuery.data.bars` filtered by `hasFiniteOhlc`, the same
  // source/filter the effect's own `finiteBars` uses), so
  // `tideRegionHelp.interpretValue`'s Bullish/Bearish/Neutral percentages
  // can never describe a different set of bars than what's actually shaded
  // on the chart -- the same data-source-consistency requirement this task
  // note flags (PR #152 round 2 legend/chart mismatch).
  const tideRegionPoints =
    bars.length > 0 && indicatorsQuery.data
      ? selectVisibleIndicatorPoints(
          indicatorsQuery.data.points,
          bars[0].date,
          bars[bars.length - 1].date,
        )
      : []

  // Support/resistance zones for the legend below. Post-review fix (PR
  // #152 retry round 2): this used to read the raw, unfiltered `zones`
  // array (and a stale `Math.min(zones.length, MAX_DISPLAYED_ZONES)`
  // formula) for the legend's "Showing N of M" count and its
  // "Nearest to the latest close" reading -- which could name a zone the
  // chart-drawing effect above had actually excluded via the relevance
  // filter (e.g. a pre-split-era AAPL zone at $0.34-0.35 reported as
  // "nearest" to a $336 close while 0 zones were actually drawn). Now this
  // runs the exact same `selectDisplayedZones` (relevance-filtered +
  // strongest-N-capped) call, with the same `bars.length < 2` guard the
  // effect uses (`bars` here is already `historyQuery.data.bars` filtered
  // by `hasFiniteOhlc`, the same source/filter the effect's own
  // `finiteBars` uses), so the legend can never describe a zone that isn't
  // actually on the chart.
  const zones = analysisQuery.data?.support_resistance_zones ?? []
  const zoneReferencePrice = bars.length >= 2 ? bars.at(-1)?.close : undefined
  const displayedZones =
    zoneReferencePrice != null
      ? selectDisplayedZones(zones, zoneReferencePrice, visibleBarPriceSpan(bars))
      : []

  // Follow-up fix (frontend-support-resistance-overlay-followups, checklist
  // item 1): `falseBreakoutHelp.interpretValue`'s "Most recent" reading used
  // to be filtered by `displayedZones` only, NOT further windowed by the
  // currently visible date range the way `buildFalseBreakoutMarkers`'
  // marker and the dashed "False-breakout stop" price line both already
  // are -- so it could describe a specific breakout (exact dates + stop
  // price) whose marker/price-line wasn't actually rendered in the current
  // range view. `mostRecentBreakoutZone` runs the exact same selection
  // (`mostRecentFalseBreakoutZone`, exported from metricHelpContent.ts) the
  // legend text itself uses, and `falseBreakoutInVisibleRange` checks its
  // `reentry_date` against the same `isFalseBreakoutInRange` window the
  // chart-drawing effect's marker/price-line use -- so the legend can never
  // silently disagree with what's actually plotted. Decision (this task's
  // `decisions` entry): follows the divergence/Kangaroo Tail precedent
  // (keep describing the real episode, append a caveat + dim the legend
  // swatch when it's out of range) rather than filtering the search to
  // only in-range breakouts.
  const mostRecentBreakoutZone = mostRecentFalseBreakoutZone(displayedZones)
  const falseBreakoutInVisibleRange =
    mostRecentBreakoutZone == null || bars.length === 0
      ? true
      : isFalseBreakoutInRange(
          mostRecentBreakoutZone.false_breakout,
          bars[0].date,
          bars[bars.length - 1].date,
        )

  // The single currently-qualifying divergence, read directly from
  // `/analysis` -- the same value both the divergence-overlay effect above
  // and the legend/balloon below draw from, so they can never disagree
  // about which divergence (if any) is being shown (see the legend's own
  // comment for why there's no separate filtered/"displayed" variant to
  // keep in sync here, unlike `displayedZones` above).
  const divergence = analysisQuery.data?.divergence ?? null

  // Post-review fix (PR #158): whether `divergence` (if any) is actually
  // drawn on the chart this render -- the same `isDivergenceInRange` check
  // the divergence-overlay effect above runs against `finiteBars`, computed
  // here from `bars` (already `historyQuery.data.bars` filtered by
  // `hasFiniteOhlc`, same source) so the legend can describe whether the
  // divergence is currently plotted without duplicating the effect's own
  // windowing logic differently.
  const divergenceInVisibleRange =
    divergence != null && bars.length > 0
      ? isDivergenceInRange(divergence, bars[0].date, bars[bars.length - 1].date)
      : false

  // The single most recently confirmed Kangaroo Tail, read directly from
  // `/analysis` -- same "one value, no separate filtered variant" pattern
  // as `divergence` above (there's nothing to filter/cap for a single
  // pattern the way `displayedZones` filters/caps a list).
  const kangarooTail = analysisQuery.data?.kangaroo_tail ?? null

  // Whether `kangarooTail` (if any) is actually drawn on the chart this
  // render -- same `isKangarooTailInRange` check the overlay effect above
  // runs, computed here from `bars` (same source/filter) so the legend can
  // describe whether the tail is currently plotted without duplicating the
  // effect's own windowing logic differently.
  const kangarooTailInVisibleRange =
    kangarooTail != null && bars.length > 0
      ? isKangarooTailInRange(kangarooTail, bars[0].date, bars[bars.length - 1].date)
      : false

  // The tail bar's own OHLC bar, looked up by date from the currently
  // fetched `/history` bars -- see `kangarooTailHelp`'s own doc comment
  // (`metricHelpContent.ts`) for why this lookup (rather than a field on
  // `KangarooTailOut` itself) is how the legend gets the open/close values
  // its explanation needs. Uses the unfiltered `historyQuery.data?.bars`
  // (not `bars`, which drops a still-forming latest bar) since the tail bar
  // itself, being a past confirmed bar, was never the one that could be
  // still-forming -- but a plain `.find` over the raw array is simplest and
  // correct either way.
  const kangarooTailBar =
    kangarooTail != null
      ? historyQuery.data?.bars.find((bar) => bar.date === kangarooTail.tail_date)
      : undefined

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap' }}>
        <ToggleButtonGroup
          size="small"
          value={range}
          exclusive
          onChange={handleRangeChange}
          aria-label="Price history range"
        >
          {RANGE_OPTIONS.map((option) => (
            <ToggleButton key={option.value} value={option.value}>
              {option.label}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>

        <ToggleButtonGroup
          size="small"
          value={interval}
          exclusive
          onChange={handleIntervalChange}
          aria-label="Price history interval"
        >
          <ToggleButton value="daily">Daily</ToggleButton>
          <ToggleButton value="weekly">Weekly</ToggleButton>
        </ToggleButtonGroup>
      </Stack>

      {/*
        Channel/value-zone legend + MetricHelp affordances (frontend-
        channel-overlay). Gated the same as the rest of the overlay (daily
        interval, indicators loaded, at least one point) since both plotted
        elements come from `/indicators`, same as the EMA13/EMA26 overlay
        above them on this same chart.
      */}
      {showOverlaySection && indicatorsQuery.isSuccess && latestIndicatorPoint && (
        <Stack direction="row" spacing={3} useFlexGap sx={{ flexWrap: 'wrap' }}>
          <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
            <Box
              sx={{
                width: 14,
                height: 0,
                borderTop: '2px dashed',
                borderColor: 'info.main',
              }}
            />
            <Typography variant="caption" color="text.secondary">
              Channel (Autoenvelope)
            </Typography>
            <MetricHelp
              metricLabel={channelHelp.metricLabel}
              definition={channelHelp.definition}
              elderContext={channelHelp.elderContext}
              valueInterpretation={channelHelp.interpretValue(
                latestIndicatorPoint.channel_upper,
                latestIndicatorPoint.channel_lower,
                latestClose,
              )}
            />
          </Stack>
          <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
            <Box
              sx={{
                width: 14,
                height: 14,
                bgcolor: `${theme.palette.info.main}33`,
                border: '1px solid',
                borderColor: 'info.main',
              }}
            />
            <Typography variant="caption" color="text.secondary">
              Value Zone (EMA 13-26)
            </Typography>
            <MetricHelp
              metricLabel={valueZoneHelp.metricLabel}
              definition={valueZoneHelp.definition}
              elderContext={valueZoneHelp.elderContext}
              valueInterpretation={valueZoneHelp.interpretValue(
                latestIndicatorPoint.ema_13,
                latestIndicatorPoint.ema_26,
              )}
            />
          </Stack>
          <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
            <Stack direction="row" spacing={0.25}>
              <Box
                sx={{
                  width: 10,
                  height: 14,
                  bgcolor: `${theme.palette.signal.buy}${TIDE_REGION_FILL_ALPHA}`,
                  border: '1px solid',
                  borderColor: 'signal.buy',
                }}
              />
              <Box
                sx={{
                  width: 10,
                  height: 14,
                  bgcolor: `${theme.palette.signal.hold}${TIDE_REGION_FILL_ALPHA}`,
                  border: '1px solid',
                  borderColor: 'signal.hold',
                }}
              />
              <Box
                sx={{
                  width: 10,
                  height: 14,
                  bgcolor: `${theme.palette.signal.sell}${TIDE_REGION_FILL_ALPHA}`,
                  border: '1px solid',
                  borderColor: 'signal.sell',
                }}
              />
            </Stack>
            <Typography variant="caption" color="text.secondary">
              Tide Background (Bullish / Neutral / Bearish)
            </Typography>
            <MetricHelp
              metricLabel={tideRegionHelp.metricLabel}
              definition={tideRegionHelp.definition}
              elderContext={tideRegionHelp.elderContext}
              valueInterpretation={tideRegionHelp.interpretValue(tideRegionPoints)}
            />
          </Stack>
        </Stack>
      )}

      {/*
        Support/resistance zone legend + MetricHelp affordances (frontend-
        support-resistance-overlay). Gated on the chart itself having bars
        and at least one zone actually DISPLAYED (`displayedZones`, not the
        raw `zones` count -- post-review fix, PR #152 retry round 2: a
        legend for zones that were all filtered out as irrelevant would
        describe nothing actually on the chart) -- unlike the channel/
        value-zone legend above, NOT on `showOverlaySection`/`overlayEnabled`,
        since zones come from `/analysis` (interval-agnostic), not
        `/indicators`.
      */}
      {historyQuery.isSuccess &&
        hasBars &&
        analysisQuery.isSuccess &&
        displayedZones.length > 0 && (
          <Stack direction="row" spacing={3} useFlexGap sx={{ flexWrap: 'wrap' }}>
            <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
              <Box
                sx={{
                  width: 14,
                  height: 14,
                  bgcolor: `${theme.palette.signal.sell}33`,
                  border: '1px solid',
                  borderColor: 'signal.sell',
                }}
              />
              <Typography variant="caption" color="text.secondary">
                Support/Resistance Zones
              </Typography>
              <MetricHelp
                metricLabel={supportResistanceZoneHelp.metricLabel}
                definition={supportResistanceZoneHelp.definition}
                elderContext={supportResistanceZoneHelp.elderContext}
                valueInterpretation={supportResistanceZoneHelp.interpretValue(
                  zones,
                  displayedZones,
                  latestClose,
                )}
              />
            </Stack>
            <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
              <Box
                sx={{
                  width: 14,
                  height: 0,
                  borderTop: '2px dashed',
                  borderColor: 'warning.main',
                  opacity: falseBreakoutInVisibleRange ? 1 : 0.4,
                }}
              />
              <Typography variant="caption" color="text.secondary">
                False Breakout
                {mostRecentBreakoutZone != null &&
                  !falseBreakoutInVisibleRange &&
                  ' (not in current range)'}
              </Typography>
              <MetricHelp
                metricLabel={falseBreakoutHelp.metricLabel}
                definition={falseBreakoutHelp.definition}
                elderContext={falseBreakoutHelp.elderContext}
                valueInterpretation={falseBreakoutHelp.interpretValue(
                  displayedZones,
                  falseBreakoutInVisibleRange,
                )}
              />
            </Stack>
          </Stack>
        )}

      {/*
        Divergence legend + MetricHelp affordance (frontend-divergence-
        markers). Reads `analysisQuery.data.divergence` directly -- the
        exact same value the divergence-overlay effect above draws from,
        with no separate "displayed" filtering/capping step to drift out of
        sync with (unlike the zone legend above, which needs its own
        `displayedZones` precisely because there IS a relevance-filter/cap
        step between the raw `zones` array and what's actually drawn -- see
        that legend's own comment for the bug this pattern exists to avoid).
        Still gated on `divergence` alone (not `divergenceInVisibleRange`
        too) -- Decision (post-review fix, PR #158, this task's `decisions`
        entry): the legend stays visible and keeps naming the real
        divergence even when the current range selection excludes it from
        the chart itself, with `divergenceHelp.interpretValue`'s own
        `inVisibleRange` clause explaining why nothing is drawn right now --
        chosen over hiding the row entirely (as the zone legend does once
        `displayedZones` empties) because a divergence's out-of-range-ness is
        a temporary, range-selection-dependent state for a single real
        signal, not a permanent exclusion the way a zone failing the
        relevance filter is; hiding it here would read as "no divergence
        exists" rather than "not shown at this range".
      */}
      {historyQuery.isSuccess && hasBars && analysisQuery.isSuccess && divergence && (
        <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
          <Box
            sx={{
              width: 12,
              height: 12,
              borderRadius: '50%',
              bgcolor: 'divergence.main',
              opacity: divergenceInVisibleRange ? 1 : 0.4,
            }}
          />
          <Typography variant="caption" color="text.secondary">
            Divergence{!divergenceInVisibleRange && ' (not in current range)'}
          </Typography>
          <MetricHelp
            metricLabel={divergenceHelp.metricLabel}
            definition={divergenceHelp.definition}
            elderContext={divergenceHelp.elderContext}
            valueInterpretation={divergenceHelp.interpretValue(
              divergence,
              divergenceInVisibleRange,
            )}
          />
        </Stack>
      )}

      {/*
        Kangaroo Tail legend + MetricHelp affordance (frontend-kangaroo-
        tail-markers). Same "reads directly from `/analysis`, no separate
        filtered variant, stays visible even when out of the current range"
        posture as the divergence legend directly above -- see that block's
        own comment for the rationale, which applies identically here (a
        single, real, currently-confirmed pattern for this ticker, whose
        out-of-range-ness is a temporary range-selection state, not a
        permanent exclusion).
      */}
      {historyQuery.isSuccess && hasBars && analysisQuery.isSuccess && kangarooTail && (
        <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
          <Box
            sx={{
              width: 12,
              height: 12,
              bgcolor: 'kangarooTail.main',
              opacity: kangarooTailInVisibleRange ? 1 : 0.4,
            }}
          />
          <Typography variant="caption" color="text.secondary">
            Kangaroo Tail{!kangarooTailInVisibleRange && ' (not in current range)'}
          </Typography>
          <MetricHelp
            metricLabel={kangarooTailHelp.metricLabel}
            definition={kangarooTailHelp.definition}
            elderContext={kangarooTailHelp.elderContext}
            valueInterpretation={kangarooTailHelp.interpretValue(
              kangarooTail,
              kangarooTailBar,
              kangarooTailInVisibleRange,
            )}
          />
        </Stack>
      )}

      {historyQuery.isLoading && (
        <LoadingState message={`Loading price history for ${ticker}...`} />
      )}

      {historyQuery.isError && <ErrorState error={historyQuery.error} />}

      {historyQuery.isSuccess && !hasBars && (
        <EmptyState message={`No price history available for ${ticker}.`} />
      )}

      {historyQuery.isSuccess && hasBars && (
        <Box
          ref={containerRef}
          data-testid="price-chart-canvas"
          sx={{ width: '100%', height: CHART_HEIGHT }}
        />
      )}

      {/*
        Signal-overlay states, gated on `showOverlaySection` above. These
        never block the candlestick chart itself from rendering: a slow/
        failed/empty `/indicators` response degrades to "no overlay", not
        "no chart" — the chart's own OHLCV data is the primary content here.
      */}
      {showOverlaySection && indicatorsQuery.isLoading && (
        <LoadingState message={`Loading signal overlay for ${ticker}...`} />
      )}

      {/*
        Post-review fix (frontend-position-risk-columns-followups-followups-
        followups-followups): the indicators-ErrorState below is gated on
        `overlayEnabled` alone, NOT `showOverlaySection` (which also requires
        `historyQuery.isSuccess && hasBars` — a condition about price
        history, unrelated to whether `/indicators` itself failed).
        `OscillatorChart`/`VolumeIndicatorsChart`/`TrendStrengthChart` all
        suppress their own `indicatorsQuery.isError` ErrorState now (their
        own `errorSurfacedBySibling` prop, set by `StockCharts.tsx`), relying
        on this one to be the shared failure's sole surface — but while it
        was still gated on `showOverlaySection`, a `GET
        /api/stocks/{ticker}/history` failure (or a zero-usable-bars success,
        e.g. every bar filtered out by `hasFiniteOhlc`) made
        `showOverlaySection` false, so a genuine, simultaneous `/indicators`
        failure never rendered anywhere at all. `overlayEnabled` (daily
        interval only — see its own comment above) is the only gate that's
        actually about whether `/indicators` is even fetched at all: when
        it's `false`, `useIndicatorHistory` itself is disabled and
        `indicatorsQuery.isError` can never be `true`, so this condition
        still never fires spuriously while a weekly interval is selected.
        Decision (this task's `decisions` entry): un-gating this one state
        from `showOverlaySection` rather than having one of the three
        siblings fall back to its own ErrorState when `!showOverlaySection`
        — see that entry for the alternative considered and why this was
        chosen instead.
      */}
      {overlayEnabled && indicatorsQuery.isError && (
        <ErrorState error={indicatorsQuery.error} />
      )}

      {showOverlaySection &&
        indicatorsQuery.isSuccess &&
        indicatorsQuery.data.points.length === 0 && (
          <EmptyState message={`No signal history available for ${ticker}.`} />
        )}

      {/*
        Divergence-marker click-to-explain balloon (frontend-divergence-
        markers). Same `divergenceHelp.interpretValue` content as the legend
        row above -- one explanation source, two ways to reach it (the
        legend's own MetricHelp icon, or clicking either marker directly on
        the chart). `divergence` gates `open` too, not just `content`: if
        the ticker/data changed since the balloon was opened and no longer
        has a divergence, there's nothing left to explain.
      */}
      <AnchoredInfoBalloon
        open={divergenceBalloonAnchor !== null && divergence !== null}
        anchorPosition={divergenceBalloonAnchor}
        onClose={() => setDivergenceBalloonAnchor(null)}
        title={divergenceHelp.metricLabel}
        ariaLabel="Divergence details"
        content={
          <Typography variant="body2">
            {divergence
              ? divergenceHelp.interpretValue(divergence, divergenceInVisibleRange)
              : null}
          </Typography>
        }
      />
    </Stack>
  )
}
