import Box from '@mui/material/Box'
import Stack from '@mui/material/Stack'
import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import { useTheme } from '@mui/material/styles'
import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react'
import type { HistoryInterval, HistoryResponse, IndicatorHistoryPoint } from '../../../api/stocks'
import EmptyState from '../../../components/common/EmptyState/EmptyState'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import { useIndicatorHistory } from '../hooks/useIndicatorHistory'
import { useStockHistory } from '../hooks/useStockHistory'

export interface PriceChartProps {
  ticker: string
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

const DEFAULT_RANGE = '1y'
const DEFAULT_INTERVAL: HistoryInterval = 'daily'
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

/** A single point from `/indicators`, projected into the three series this
 * overlay plots — computed in one pass over `points` (see `buildOverlayData`
 * below) rather than three separate `.map()`/loop passes over the same
 * array, per this task's followups review comment. */
interface OverlayData {
  ema13: { time: Time; value: number }[]
  ema26: { time: Time; value: number }[]
  markers: SeriesMarker<Time>[]
}

/**
 * Projects `/indicators` points into the EMA13/EMA26 line data plus BUY/SELL
 * transition markers, in a single pass. The marker logic builds one marker
 * per *transition* into a BUY or SELL signal (i.e. the bar differs from the
 * previous point, and the previous point isn't undefined — so the very
 * first point is treated as a transition from "no signal" too), not one
 * marker per bar carrying that signal — Decision (see this component's own
 * doc comment and this task's `decisions` entry): marking every BUY/SELL bar
 * in e.g. a multi-week BUY run would bury the actually meaningful "Trigger
 * fired" moments (docs/Analyse.md §5) under a wall of identical arrows. HOLD
 * never gets a marker — there's no Elder-Ray/Trigger event to mark for it,
 * only the absence of one.
 */
function buildOverlayData(
  points: readonly IndicatorHistoryPoint[],
  colors: { buy: string; sell: string },
): OverlayData {
  const ema13: OverlayData['ema13'] = []
  const ema26: OverlayData['ema26'] = []
  const markers: SeriesMarker<Time>[] = []
  let previousSignal: IndicatorHistoryPoint['signal'] | undefined
  for (const point of points) {
    const time = point.date as Time
    ema13.push({ time, value: point.ema_13 })
    ema26.push({ time, value: point.ema_26 })
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
  return { ema13, ema26, markers }
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
 */
export default function PriceChart({ ticker }: PriceChartProps) {
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

    const chart = createChart(container, {
      autoSize: true,
      layout: { background: { color: 'transparent' } },
    })
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

    const { ema13, ema26, markers } = buildOverlayData(points, {
      buy: theme.palette.signal.buy,
      sell: theme.palette.signal.sell,
    })

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

    const markersPlugin = createSeriesMarkers(series, markers)

    return () => {
      // See the block comment above: skip if the candlestick effect's
      // cleanup already disposed this chart/series (refs no longer match).
      if (chartRef.current !== chart || seriesRef.current !== series) {
        return
      }
      chart.removeSeries(ema13Series)
      chart.removeSeries(ema26Series)
      markersPlugin.detach()
    }
  }, [historyQuery.data, indicatorsQuery.data, overlayEnabled, theme])

  function handleRangeChange(_event: ReactMouseEvent<HTMLElement>, value: string | null) {
    if (value !== null) {
      setRange(value)
    }
  }

  function handleIntervalChange(
    _event: ReactMouseEvent<HTMLElement>,
    value: HistoryInterval | null,
  ) {
    if (value !== null) {
      setInterval(value)
    }
  }

  // Shared gate for the signal-overlay states below: the underlying
  // candlestick chart must already have something to overlay onto
  // (`historyQuery.isSuccess && hasBars`), and the overlay must be
  // applicable at all (`overlayEnabled` — daily interval only, see above).
  // Computed once rather than repeated across each overlay state's own JSX
  // guard.
  const showOverlaySection = historyQuery.isSuccess && hasBars && overlayEnabled

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

      {showOverlaySection && indicatorsQuery.isSuccess && indicatorsQuery.data.points.length === 0 && (
        <EmptyState message={`No signal history available for ${ticker}.`} />
      )}
    </Stack>
  )
}
