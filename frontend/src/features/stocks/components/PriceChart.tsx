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
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react'
import type {
  HistoryInterval,
  HistoryResponse,
  IndicatorHistoryPoint,
  SupportResistanceZone,
} from '../../../api/stocks'
import EmptyState from '../../../components/common/EmptyState/EmptyState'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import { useIndicatorHistory } from '../hooks/useIndicatorHistory'
import { useStockAnalysis } from '../hooks/useStockAnalysis'
import { useStockHistory } from '../hooks/useStockHistory'
import { bringSeriesToFront, createBaseChart, isFiniteNumber } from '../../../utils/chart'
import {
  channelHelp,
  falseBreakoutHelp,
  supportResistanceZoneHelp,
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

/**
 * True when `zone`'s `[lower, upper]` band overlaps the window
 * `referencePrice * (1 - ZONE_RELEVANCE_PRICE_RATIO)` ..
 * `referencePrice * (1 + ZONE_RELEVANCE_PRICE_RATIO)` -- i.e. within 50%
 * of the reference price either way. See `ZONE_RELEVANCE_PRICE_RATIO`'s own
 * comment and this task's `decisions` entry for why a price-ratio window
 * (rather than e.g. the currently visible bars' own high/low span) was
 * chosen as the relevance definition.
 */
function isZoneRelevant(zone: SupportResistanceZone, referencePrice: number): boolean {
  const windowMin = referencePrice * (1 - ZONE_RELEVANCE_PRICE_RATIO)
  const windowMax = referencePrice * (1 + ZONE_RELEVANCE_PRICE_RATIO)
  return zone.upper >= windowMin && zone.lower <= windowMax
}

/**
 * Zones actually eligible to be drawn on the chart: filtered to ones
 * relevant to `referencePrice` (see `isZoneRelevant`), THEN capped to the
 * strongest `MAX_DISPLAYED_ZONES` (zones arrive already sorted
 * strongest-first, so this is a plain `.slice`) -- in that order, so the
 * relevance filter always runs before the cap and a distant zone can never
 * consume one of the 6 display slots. Shared by both `buildZoneRenderData`
 * (the shaded bands) and `buildFalseBreakoutMarkers` (their false-breakout
 * markers/stop lines) so the two stay in lockstep: a false breakout is only
 * ever marked for a zone whose band is actually drawn.
 */
function selectDisplayedZones(
  zones: readonly SupportResistanceZone[],
  referencePrice: number,
): SupportResistanceZone[] {
  return zones
    .filter((zone) => isZoneRelevant(zone, referencePrice))
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
    if (!breakout) {
      continue
    }
    if (breakout.reentry_date < firstDate || breakout.reentry_date > lastDate) {
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
 * Lightweight Charts line series (Screen 1's trend-following pair, per
 * docs/Analyse.md §2/§4), plus BUY/SELL markers via the series-markers
 * plugin at each bar where the signal actually changed (see
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
    const displayedZones = selectDisplayedZones(zones, referencePrice)
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
      if (
        breakout == null ||
        breakout.reentry_date < firstDate ||
        breakout.reentry_date > lastDate
      ) {
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
    zoneReferencePrice != null ? selectDisplayedZones(zones, zoneReferencePrice) : []

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
                }}
              />
              <Typography variant="caption" color="text.secondary">
                False Breakout
              </Typography>
              <MetricHelp
                metricLabel={falseBreakoutHelp.metricLabel}
                definition={falseBreakoutHelp.definition}
                elderContext={falseBreakoutHelp.elderContext}
                valueInterpretation={falseBreakoutHelp.interpretValue(displayedZones)}
              />
            </Stack>
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

      {showOverlaySection && indicatorsQuery.isError && (
        <ErrorState error={indicatorsQuery.error} />
      )}

      {showOverlaySection &&
        indicatorsQuery.isSuccess &&
        indicatorsQuery.data.points.length === 0 && (
          <EmptyState message={`No signal history available for ${ticker}.`} />
        )}
    </Stack>
  )
}
