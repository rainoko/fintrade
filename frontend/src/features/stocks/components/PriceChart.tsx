import Box from '@mui/material/Box'
import Stack from '@mui/material/Stack'
import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'
import {
  AreaSeries,
  CandlestickSeries,
  createSeriesMarkers,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react'
import type {
  HistoryInterval,
  HistoryResponse,
  IndicatorHistoryPoint,
} from '../../../api/stocks'
import EmptyState from '../../../components/common/EmptyState/EmptyState'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import { useIndicatorHistory } from '../hooks/useIndicatorHistory'
import { useStockHistory } from '../hooks/useStockHistory'
import { createBaseChart, isFiniteNumber } from '../../../utils/chart'
import { channelHelp, valueZoneHelp } from './metricHelpContent'

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
  return { ema13, ema26, channelUpper, channelLower, valueZoneTop, valueZoneBottom, markers }
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

    // Value-zone shading, added *before* the EMA/channel line series below
    // so those lines render crisply on top of it (Lightweight Charts draws
    // later-added series above earlier ones, on the same pane). Two
    // `AreaSeries` in a "fill, then mask" pair, since Lightweight Charts has
    // no native "fill the region between two arbitrary line series"
    // primitive (only fill-from-a-line-to-the-bottom-of-the-pane, or a
    // custom series plugin -- overkill for this): `zoneTopSeries` paints a
    // translucent fill from `valueZoneTop` (the pointwise-higher of
    // EMA13/EMA26 at each bar) down to the bottom of the visible range,
    // then `zoneBottomSeries` -- added after, so on top -- repaints
    // everything from `valueZoneBottom` down in the *chart's own opaque
    // background color*, erasing the portion below the lower EMA and
    // leaving only the true "value zone" between the two visibly shaded.
    // This depends on the chart's `layout.background` actually being opaque
    // white (`theme.palette.background.paper`, matching `createBaseChart`'s
    // transparent layer showing this page's plain white background through
    // it) -- see this task's `decisions` entry for why that assumption is
    // safe today (this app has no dark-mode/alternate-theme support at all)
    // but would need revisiting if one were ever added.
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
