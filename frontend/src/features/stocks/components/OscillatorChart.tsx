import Box from '@mui/material/Box'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTheme, type Theme } from '@mui/material/styles'
import {
  HistogramSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from 'lightweight-charts'
import { useEffect, useRef } from 'react'
import type { IndicatorHistoryPoint, IndicatorHistoryResponse } from '../../../api/stocks'
import EmptyState from '../../../components/common/EmptyState/EmptyState'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import { useIndicatorHistory } from '../hooks/useIndicatorHistory'
import { createBaseChart } from '../../../utils/chart'

export interface OscillatorChartProps {
  ticker: string
  /** '<N>d' | '<N>w' | '<N>m' | '<N>y' | 'max' (see API.md) — kept in sync
   * with `PriceChart`'s own range selection by the shared `StockCharts`
   * wrapper, so both panes always plot the same window. */
  range: string
  /**
   * `GET /api/stocks/{ticker}/indicators` has no `interval` param — every
   * value it returns is daily-cadence (see API.md / this component's own
   * doc comment below). `StockCharts` passes `interval === 'daily'` here,
   * the same convention `PriceChart`'s own EMA/signal overlay already uses
   * for the same reason. Defaults to `true` so this component works
   * standalone (e.g. in isolation in a test) without a caller needing to
   * think about an interval it may not otherwise track.
   */
  enabled?: boolean
}

const CHART_HEIGHT = 420
const STOCHASTIC_OVERSOLD = 30
const STOCHASTIC_OVERBOUGHT = 70

interface OscillatorSeriesData {
  stochastic: { time: Time; value: number }[]
  forceIndex: { time: Time; value: number; color: string }[]
  macdHistogram: { time: Time; value: number; color: string }[]
}

/**
 * `stochastic_k`/`force_index_2ema` are declared `number | null | undefined`
 * in the generated OpenAPI type (backend/app/api/schemas.py's
 * `IndicatorHistoryPoint` was widened to `float | None` for exactly this
 * reason — see the frontend-oscillator-chart-followups task's `decisions`
 * entry), since the runtime response can legitimately return `null` for
 * early bars still inside an indicator's warm-up window (e.g. Stochastic
 * %K(5,3,3) needs (k_period - 1) + (smooth - 1) prior bars — 6 with the
 * current defaults) — confirmed live via GET
 * /api/stocks/AAPL/indicators?range=max, which returns points with
 * stochastic_k/force_index_2ema literally `null`. `macd_histogram` stays
 * non-nullable (EMA-seeded indicators never produce NaN, even on the first
 * bar) but is still run through this same guard for defense-in-depth,
 * matching `PriceChart.tsx`'s `hasFiniteOhlc` guard for OHLCV bars.
 *
 * The type fix alone doesn't remove the need for this runtime guard:
 * Lightweight Charts' `setData` throws synchronously on a non-numeric
 * value, which — uncaught — crashes the whole app via the root
 * `AppErrorBoundary`, not just this pane, and an honestly-`null`-typed
 * value is exactly as unplottable as a dishonestly-`number`-typed one that
 * happens to be `null` at runtime — a type only prevents a *type* error, not
 * a value TradingView's chart library can't render. `unknown` (rather than
 * the field's own `number | null | undefined` type) is still used for the
 * parameter here so this guard keeps working unconditionally regardless of
 * a caller's declared type.
 */
function isFiniteValue(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

/**
 * Projects `/indicators` points into the three oscillator series this pane
 * plots, in a single pass (same "build once, not three separate `.map()`
 * passes" convention as `PriceChart.tsx`'s `buildOverlayData`). Each series
 * is filtered independently by `isFiniteValue` (a point with a null
 * `stochastic_k` but a valid `force_index_2ema` still contributes to the
 * Force Index series) — a still-warming-up point is simply omitted from
 * that one series (Lightweight Charts renders a gap across a missing
 * time point, not a broken line), rather than the whole series being
 * suppressed. Force Index/MACD Histogram bars are colored by sign (>= 0 vs
 * < 0) using the theme's buy/sell colors — a conventional
 * histogram-coloring choice (every mainstream charting platform colors a
 * MACD histogram this way), not a literal claim that a positive bar IS a
 * BUY signal: Analyse.md §2 is explicit that Force Index's sign is only a
 * buying/selling *cue* in combination with the prevailing trend, which this
 * pane doesn't (and shouldn't) recompute — see this task's `decisions`
 * entry.
 */
function buildOscillatorSeriesData(
  points: readonly IndicatorHistoryPoint[],
  colors: { positive: string; negative: string },
): OscillatorSeriesData {
  const stochastic: OscillatorSeriesData['stochastic'] = []
  const forceIndex: OscillatorSeriesData['forceIndex'] = []
  const macdHistogram: OscillatorSeriesData['macdHistogram'] = []
  for (const point of points) {
    const time = point.date as Time
    if (isFiniteValue(point.stochastic_k)) {
      stochastic.push({ time, value: point.stochastic_k })
    }
    if (isFiniteValue(point.force_index_2ema)) {
      forceIndex.push({
        time,
        value: point.force_index_2ema,
        color: point.force_index_2ema >= 0 ? colors.positive : colors.negative,
      })
    }
    if (isFiniteValue(point.macd_histogram)) {
      macdHistogram.push({
        time,
        value: point.macd_histogram,
        color: point.macd_histogram >= 0 ? colors.positive : colors.negative,
      })
    }
  }
  return { stochastic, forceIndex, macdHistogram }
}

/**
 * Adds one histogram pane with a dotted zero baseline — the setup shared,
 * before this helper, near-identically between the Force Index and MACD
 * Histogram panes (same series options shape, same zero `createPriceLine`)
 * with only the title/paneIndex/data differing. See this task's `decisions`
 * entry for why a zero baseline rather than a documented threshold pair
 * (like Stochastic's 30/70) is used for both.
 */
function addZeroBaselineHistogramPane(
  chart: IChartApi,
  paneIndex: number,
  title: string,
  data: OscillatorSeriesData['forceIndex'],
  theme: Theme,
): ISeriesApi<'Histogram'> {
  const series = chart.addSeries(
    HistogramSeries,
    { title, priceLineVisible: false, lastValueVisible: false },
    paneIndex,
  )
  series.setData(data)
  series.createPriceLine({
    price: 0,
    color: theme.palette.text.secondary,
    lineWidth: 1,
    lineStyle: LineStyle.Dotted,
    axisLabelVisible: false,
    title: '',
  })
  return series
}

/**
 * Historical oscillator pane for Screen 2 ("the Wave", docs/Analyse.md §2):
 * Stochastic %K(5,3,3), Force Index (2-period EMA), and MACD Histogram
 * (daily — the Impulse System's slope input, docs/Analyse.md §4 row 2/§
 * "Impulse System"), each sourced from `GET /api/stocks/{ticker}/indicators`
 * via the shared `useIndicatorHistory` hook (same hook, same query key
 * convention `PriceChart.tsx`'s signal overlay already uses — the query is
 * deduplicated by TanStack Query, not fetched twice, when both panes are
 * mounted together with the same `ticker`/`range`). No indicator/signal math
 * happens here — every plotted value comes straight from the backend
 * response, per Frontend.md §5's "backend computes, frontend displays" rule.
 *
 * Rendered as three separate Lightweight Charts panes within ONE chart
 * instance (native multi-pane support, `chart.addSeries(definition, opts,
 * paneIndex)`) rather than one shared pane — see this task's `decisions`
 * entry for why: Stochastic (a bounded 0-100 oscillator) and Force Index
 * (an unbounded, volume-weighted value that can run into the tens of
 * thousands) would make each other unreadable sharing one y-axis, and MACD
 * Histogram sits on yet another scale again. All three panes share the same
 * time (x) axis natively, since they belong to the same `IChartApi`
 * instance — no manual cross-chart range syncing needed. Stochastic gets
 * dashed reference lines at the documented 30/70 oversold/overbought
 * thresholds (docs/Analyse.md §4); Force Index and MACD Histogram get a
 * dotted zero baseline instead, since Analyse.md doesn't document a numeric
 * threshold for either — only their sign/spike behavior matters.
 *
 * `IndicatorsPanel.tsx` (fed by `/analysis`) remains the latest-value-only
 * counterpart for MACD Histogram's point-in-time reading; `ScreensPanel.tsx`
 * is the latest-value-only counterpart for Stochastic %K/Force Index. This
 * component is their historical-trend complement, not a replacement.
 */
export default function OscillatorChart({
  ticker,
  range,
  enabled = true,
}: OscillatorChartProps) {
  const theme = useTheme()
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)

  const indicatorsQuery = useIndicatorHistory(ticker, { range }, { enabled })
  const points = indicatorsQuery.data?.points ?? []
  const hasPoints = points.length > 0

  // Depends on `indicatorsQuery.data` itself (a new object per response)
  // rather than the `points`/`hasPoints` derived above, since those are
  // fresh references on every render regardless of whether the data
  // changed — same rationale as `PriceChart.tsx`'s own candlestick effect.
  useEffect(() => {
    const container = containerRef.current
    const data: IndicatorHistoryResponse | undefined = indicatorsQuery.data
    if (!container || !enabled || !data || data.points.length === 0) {
      return
    }

    const chart = createBaseChart(container)

    const { stochastic, forceIndex, macdHistogram } = buildOscillatorSeriesData(
      data.points,
      {
        positive: theme.palette.signal.buy,
        negative: theme.palette.signal.sell,
      },
    )

    const stochasticSeries = chart.addSeries(
      LineSeries,
      {
        color: theme.palette.primary.main,
        lineWidth: 2,
        title: 'Stochastic %K (5,3,3)',
        priceLineVisible: false,
        lastValueVisible: false,
      },
      0,
    )
    stochasticSeries.setData(stochastic)
    stochasticSeries.createPriceLine({
      price: STOCHASTIC_OVERSOLD,
      color: theme.palette.signal.buy,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'Oversold (30)',
    })
    stochasticSeries.createPriceLine({
      price: STOCHASTIC_OVERBOUGHT,
      color: theme.palette.signal.sell,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: 'Overbought (70)',
    })

    addZeroBaselineHistogramPane(chart, 1, 'Force Index (2-EMA)', forceIndex, theme)
    addZeroBaselineHistogramPane(chart, 2, 'MACD Histogram (Daily)', macdHistogram, theme)

    chart.timeScale().fitContent()
    chartRef.current = chart

    return () => {
      chart.remove()
      chartRef.current = null
    }
  }, [indicatorsQuery.data, enabled, theme])

  // `/indicators` is daily-cadence only (see the `enabled` prop's own doc
  // comment) — while a weekly interval is selected upstream, this pane has
  // nothing valid to plot at all, so it renders a short explanatory message
  // instead of silently disappearing (unlike `PriceChart`'s on-chart
  // overlay, which omits its section without a message — this pane is its
  // own standalone panel lower on the page, where a message reads as
  // informative rather than as visual clutter layered on the candlesticks;
  // see this task's `decisions` entry).
  if (!enabled) {
    return (
      <EmptyState message="Oscillators (Stochastic %K, Force Index, MACD Histogram) are only available for the Daily interval." />
    )
  }

  return (
    <Stack spacing={1}>
      <Typography variant="subtitle2" color="text.secondary">
        Oscillators (Screen 2)
      </Typography>

      {indicatorsQuery.isLoading && (
        <LoadingState message={`Loading oscillator history for ${ticker}...`} />
      )}

      {indicatorsQuery.isError && <ErrorState error={indicatorsQuery.error} />}

      {indicatorsQuery.isSuccess && !hasPoints && (
        <EmptyState message={`No oscillator history available for ${ticker}.`} />
      )}

      {indicatorsQuery.isSuccess && hasPoints && (
        <Box
          ref={containerRef}
          data-testid="oscillator-chart-canvas"
          sx={{ width: '100%', height: CHART_HEIGHT }}
        />
      )}
    </Stack>
  )
}
