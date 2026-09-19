import Box from '@mui/material/Box'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTheme, type Theme } from '@mui/material/styles'
import {
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import { useEffect, useRef, useState } from 'react'
import type {
  DivergenceOut,
  IndicatorHistoryPoint,
  IndicatorHistoryResponse,
} from '../../../api/stocks'
import { AnchoredInfoBalloon } from '../../../components/common/InfoBalloon/InfoBalloon'
import EmptyState from '../../../components/common/EmptyState/EmptyState'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import { useIndicatorHistory } from '../hooks/useIndicatorHistory'
import { useStockAnalysis } from '../hooks/useStockAnalysis'
import { createBaseChart, isFiniteNumber } from '../../../utils/chart'
import { clickedDivergenceExtreme, isDivergenceInRange } from './divergenceClick'
import { divergenceHelp, rsiHelp } from './metricHelpContent'

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
  rsi: { time: Time; value: number }[]
  forceIndex: { time: Time; value: number; color: string }[]
  macdHistogram: { time: Time; value: number; color: string }[]
}

/**
 * `stochastic_k`/`force_index_2ema`/`rsi` are declared `number | null |
 * undefined` in the generated OpenAPI type (backend/app/api/schemas.py's
 * `IndicatorHistoryPoint` was widened to `float | None` for exactly this
 * reason — see the frontend-oscillator-chart-followups task's `decisions`
 * entry), since the runtime response can legitimately return `null` for
 * early bars still inside an indicator's warm-up window (e.g. Stochastic
 * %K(5,3,3) needs (k_period - 1) + (smooth - 1) prior bars — 6 with the
 * current defaults; RSI needs 9) — confirmed live via GET
 * /api/stocks/AAPL/indicators?range=max, which returns points with
 * stochastic_k/force_index_2ema/rsi literally `null`. `macd_histogram` stays
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
 * a value TradingView's chart library can't render. The shared
 * `utils/chart.ts#isFiniteNumber` guard (promoted there by
 * frontend-channel-overlay, which needed the exact same check for its
 * channel-band overlay) is used here rather than a locally-duplicated copy.
 */
const isFiniteValue = isFiniteNumber

/**
 * Projects `/indicators` points into the four oscillator series this pane
 * plots, in a single pass (same "build once, not four separate `.map()`
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
 * entry. `rsi` (frontend-rsi-oscillator-chart) shares Stochastic's own
 * 0-100 pane rather than getting a line color that varies by sign/zone --
 * see this task's `decisions` entry for why plotting the two together, not
 * a fourth separate pane, is the point.
 */
function buildOscillatorSeriesData(
  points: readonly IndicatorHistoryPoint[],
  colors: { positive: string; negative: string },
): OscillatorSeriesData {
  const stochastic: OscillatorSeriesData['stochastic'] = []
  const rsi: OscillatorSeriesData['rsi'] = []
  const forceIndex: OscillatorSeriesData['forceIndex'] = []
  const macdHistogram: OscillatorSeriesData['macdHistogram'] = []
  for (const point of points) {
    const time = point.date as Time
    if (isFiniteValue(point.stochastic_k)) {
      stochastic.push({ time, value: point.stochastic_k })
    }
    if (isFiniteValue(point.rsi)) {
      rsi.push({ time, value: point.rsi })
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
  return { stochastic, rsi, forceIndex, macdHistogram }
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

/** Which pane (see this component's own doc comment for the pane layout)
 * a given divergence's own `indicator` belongs on -- Stochastic/RSI share
 * pane 0, MACD-Histogram is pane 2. */
function divergencePaneIndex(indicator: DivergenceOut['indicator']): 0 | 2 {
  return indicator === 'macd_histogram' ? 2 : 0
}

interface DivergenceIndicatorOverlay {
  paneIndex: 0 | 2
  /** Two points spanning `first_extreme_date`..`second_extreme_date` at
   * `first_extreme_indicator_value`/`second_extreme_indicator_value` -- the
   * connecting line a `LineSeries` plots between the two compared
   * indicator readings, on whichever pane that indicator lives on. */
  line: { time: Time; value: number }[]
  markers: SeriesMarker<Time>[]
}

/**
 * Projects the single currently-qualifying divergence
 * (`AnalysisResponse.divergence`) into a 2-point connecting line plus a
 * marker at each of its two compared *indicator* readings --
 * `first_extreme_indicator_value`/`second_extreme_indicator_value`, at
 * `first_extreme_date`/`second_extreme_date` -- on whichever pane
 * `divergence.indicator` belongs to (`divergencePaneIndex` above). The
 * indicator-value counterpart to `PriceChart.tsx`'s own
 * `buildDivergencePriceOverlay`, which plots the same divergence's *price*
 * swing points instead -- see that function's own doc comment for the
 * shared "why only the single latest divergence" / "why a distinct shape/
 * color from BUY/SELL" reasoning, which applies identically here.
 */
function buildDivergenceIndicatorOverlay(
  divergence: DivergenceOut,
  color: string,
): DivergenceIndicatorOverlay {
  const label = divergence.kind === 'bullish' ? 'Bullish divergence' : 'Bearish divergence'
  const position = divergence.kind === 'bullish' ? 'belowBar' : 'aboveBar'
  return {
    paneIndex: divergencePaneIndex(divergence.indicator),
    line: [
      {
        time: divergence.first_extreme_date as Time,
        value: divergence.first_extreme_indicator_value,
      },
      {
        time: divergence.second_extreme_date as Time,
        value: divergence.second_extreme_indicator_value,
      },
    ],
    markers: [
      { time: divergence.first_extreme_date as Time, position, shape: 'circle', color, text: label },
      { time: divergence.second_extreme_date as Time, position, shape: 'circle', color, text: label },
    ],
  }
}

/**
 * Historical oscillator pane for Screen 2 ("the Wave", docs/Analyse.md §2):
 * Stochastic %K(5,3,3), RSI(9), Force Index (2-period EMA), and MACD
 * Histogram (daily — the Impulse System's slope input, docs/Analyse.md §4
 * row 2/§ "Impulse System"), each sourced from
 * `GET /api/stocks/{ticker}/indicators` via the shared `useIndicatorHistory`
 * hook (same hook, same query key convention `PriceChart.tsx`'s signal
 * overlay already uses — the query is deduplicated by TanStack Query, not
 * fetched twice, when both panes are mounted together with the same
 * `ticker`/`range`). No indicator/signal math happens here — every plotted
 * value comes straight from the backend response, per Frontend.md §5's
 * "backend computes, frontend displays" rule.
 *
 * Rendered as three separate Lightweight Charts panes within ONE chart
 * instance (native multi-pane support, `chart.addSeries(definition, opts,
 * paneIndex)`) rather than one shared pane per indicator — see this task's
 * `decisions` entry for why: Stochastic and RSI are both bounded 0-100
 * oscillators, so they share pane 0's y-axis (this is the whole point —
 * see below), while Force Index (an unbounded, volume-weighted value that
 * can run into the tens of thousands) and MACD Histogram each need their
 * own scale and would make pane 0 unreadable if merged into it. All panes
 * share the same time (x) axis natively, since they belong to the same
 * `IChartApi` instance — no manual cross-chart range syncing needed.
 * Stochastic/RSI share the same dashed reference lines at the documented
 * 30/70 oversold/overbought thresholds (docs/Analyse.md §4 — both
 * oscillators use this identical reference-line convention, per the same
 * doc's divergence-detection section); Force Index and MACD Histogram get a
 * dotted zero baseline instead, since Analyse.md doesn't document a numeric
 * threshold for either — only their sign/spike behavior matters.
 *
 * RSI (frontend-rsi-oscillator-chart) is plotted as a *second line on
 * Stochastic's own pane*, not a fourth separate pane — see this task's
 * `decisions` entry for why: the whole point of exposing RSI here is Elder's
 * own side-by-side comparison (docs/Analyse.md row 10, ch. 27) that RSI
 * (closing-price-only) is "less noisy" than Stochastic (which also reads
 * the high/low range) and tends to signal earlier on the same data — a
 * comparison that only reads clearly when both lines share one 0-100 axis a
 * user can look at directly, not two separate panes they'd have to
 * mentally overlay themselves. The `rsiHelp` `MetricHelp` affordance next
 * to the legend explains this comparison in the same explanatory pattern
 * every other chart element on this page uses (`metricHelpContent.ts`).
 *
 * `IndicatorsPanel.tsx` (fed by `/analysis`) remains the latest-value-only
 * counterpart for MACD Histogram's point-in-time reading; `ScreensPanel.tsx`
 * is the latest-value-only counterpart for Stochastic %K/Force Index. This
 * component is their historical-trend complement, not a replacement. RSI
 * has no `IndicatorsPanel.tsx` stat-card counterpart — the backend
 * response's `indicators.rsi` is exposed here only (see this task's
 * `decisions` entry for why this chart, not a new stat card, was the right
 * scope for this task).
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
  const latestPoint = hasPoints ? points[points.length - 1] : undefined

  // Divergence overlay (frontend-divergence-markers): a separate query from
  // `/analysis`, same dedup-by-TanStack-Query pattern `PriceChart.tsx`'s own
  // `useStockAnalysis(ticker)` call already documents -- `StockCharts.tsx`
  // mounts this component and `PriceChart` as siblings at the same time, so
  // this third call for the same ticker/query key coalesces with (rather
  // than duplicating) whichever of the other two fires first.
  const analysisQuery = useStockAnalysis(ticker)
  const divergence = analysisQuery.data?.divergence ?? null
  // Page coordinates of the last divergence-marker click, or `null` before
  // any click / once the balloon is closed -- same "coordinate-anchored
  // balloon" pattern as `PriceChart.tsx`'s own divergence-overlay effect.
  const [divergenceBalloonAnchor, setDivergenceBalloonAnchor] = useState<{
    top: number
    left: number
  } | null>(null)

  // Post-review fix (PR #158): whether `divergence` (if any) is actually
  // drawn on this pane this render -- the same `isDivergenceInRange` check
  // the chart-creation effect below runs against `data.points`, computed
  // here from the render-scope `points` array (same source) so the legend
  // can describe whether the divergence is currently plotted without
  // duplicating the effect's own windowing logic differently. See
  // `PriceChart.tsx`'s own identical `divergenceInVisibleRange` for the
  // shared rationale.
  const divergenceInVisibleRange =
    divergence != null && hasPoints
      ? isDivergenceInRange(divergence, points[0].date, points[points.length - 1].date)
      : false

  // Depends on `indicatorsQuery.data` itself (a new object per response)
  // rather than the `points`/`hasPoints` derived above, since those are
  // fresh references on every render regardless of whether the data
  // changed — same rationale as `PriceChart.tsx`'s own candlestick effect.
  // Also depends on `analysisQuery.data` (the divergence overlay's own
  // source) and `divergence` closes over whatever value was current the
  // last time this effect ran, same as every other value this effect reads
  // from render scope.
  useEffect(() => {
    const container = containerRef.current
    const data: IndicatorHistoryResponse | undefined = indicatorsQuery.data
    if (!container || !enabled || !data || data.points.length === 0) {
      return
    }

    const chart = createBaseChart(container)

    const { stochastic, rsi, forceIndex, macdHistogram } = buildOscillatorSeriesData(
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

    // RSI(9) — a second line sharing Stochastic's own pane/axis (see this
    // component's own doc comment for why), dashed and in a distinct
    // (secondary/purple) color so the two 0-100 oscillators stay visually
    // distinguishable while sitting on the exact same scale.
    const rsiSeries = chart.addSeries(
      LineSeries,
      {
        color: theme.palette.secondary.main,
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        title: 'RSI (9)',
        priceLineVisible: false,
        lastValueVisible: false,
      },
      0,
    )
    rsiSeries.setData(rsi)

    addZeroBaselineHistogramPane(chart, 1, 'Force Index (2-EMA)', forceIndex, theme)
    addZeroBaselineHistogramPane(chart, 2, 'MACD Histogram (Daily)', macdHistogram, theme)

    // Divergence overlay (frontend-divergence-markers): the single
    // currently-qualifying divergence, drawn as a connecting `LineSeries`
    // plus a `circle` marker at each of its two compared *indicator*
    // readings, on whichever pane its own `indicator` belongs to -- see
    // `buildDivergenceIndicatorOverlay`'s own doc comment. Click-to-explain
    // wired the same way as `PriceChart.tsx`'s own divergence overlay: this
    // pane's series markers have no DOM trigger of their own, so
    // `chart.subscribeClick` opens `AnchoredInfoBalloon` at the click's own
    // page coordinates instead.
    //
    // Post-review fix (PR #158, blocking finding): windowed to the
    // currently visible point range (`data.points[0].date`..
    // `data.points.at(-1).date`) via `isDivergenceInRange` -- same fix,
    // same rationale as `PriceChart.tsx`'s own divergence-overlay effect
    // (see that effect's comment and `isDivergenceInRange`'s own doc
    // comment in divergenceClick.ts): an unwindowed divergence line whose
    // own dates fall outside the visible range stretched this pane's (and
    // whichever pane the divergence's indicator belongs to's) time scale to
    // cover the gap, squashing the actual oscillator content into an
    // unreadable sliver.
    const divergenceInRange =
      divergence != null &&
      isDivergenceInRange(
        divergence,
        data.points[0].date,
        data.points[data.points.length - 1].date,
      )
    if (divergence && divergenceInRange) {
      const color = theme.palette.divergence.main
      const { paneIndex, line, markers } = buildDivergenceIndicatorOverlay(
        divergence,
        color,
      )
      const divergenceSeries = chart.addSeries(
        LineSeries,
        {
          color,
          lineWidth: 2,
          lineStyle: LineStyle.LargeDashed,
          title: 'Divergence',
          priceLineVisible: false,
          lastValueVisible: false,
        },
        paneIndex,
      )
      divergenceSeries.setData(line)
      createSeriesMarkers(divergenceSeries, markers)

      chart.subscribeClick((param: MouseEventParams<Time>) => {
        if (param.paneIndex !== paneIndex || !clickedDivergenceExtreme(divergence, param)) {
          return
        }
        const pageX = param.sourceEvent?.pageX
        const pageY = param.sourceEvent?.pageY
        if (pageX == null || pageY == null) {
          return
        }
        setDivergenceBalloonAnchor({ top: pageY, left: pageX })
      })
    }

    chart.timeScale().fitContent()
    chartRef.current = chart

    return () => {
      chart.remove()
      chartRef.current = null
    }
  }, [indicatorsQuery.data, enabled, theme, divergence])

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
      <EmptyState message="Oscillators (Stochastic %K, RSI, Force Index, MACD Histogram) are only available for the Daily interval." />
    )
  }

  return (
    <Stack spacing={1}>
      <Typography variant="subtitle2" color="text.secondary">
        Oscillators (Screen 2)
      </Typography>

      {/*
        RSI legend + MetricHelp affordance (frontend-rsi-oscillator-chart).
        Stochastic itself has no matching legend row here since it predates
        this task and its own reference lines/title are already visible on
        the chart -- only the newly-added RSI line gets one, same convention
        `PriceChart.tsx`'s channel/value-zone legend rows established (only
        the element a task actually adds gets its own MetricHelp row).
      */}
      {indicatorsQuery.isSuccess && hasPoints && (
        <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
          <Box
            sx={{
              width: 14,
              height: 0,
              borderTop: '2px dashed',
              borderColor: 'secondary.main',
            }}
          />
          <Typography variant="caption" color="text.secondary">
            RSI (9)
          </Typography>
          <MetricHelp
            metricLabel={rsiHelp.metricLabel}
            definition={rsiHelp.definition}
            elderContext={rsiHelp.elderContext}
            valueInterpretation={rsiHelp.interpretValue(
              latestPoint?.rsi,
              latestPoint?.stochastic_k,
            )}
          />
        </Stack>
      )}

      {/*
        Divergence legend + MetricHelp affordance (frontend-divergence-
        markers) -- same `divergenceHelp.interpretValue` content
        `PriceChart.tsx`'s own legend row shows, reading the exact same
        `analysisQuery.data.divergence` value the divergence overlay effect
        above draws from. Still gated on `divergence` alone, not also
        `divergenceInVisibleRange` -- same Decision (post-review fix, PR
        #158, this task's `decisions` entry) as `PriceChart.tsx`'s own
        identical legend row: stays visible and names the real divergence
        even when the current range excludes it from the chart, with
        `divergenceHelp.interpretValue`'s own `inVisibleRange` clause
        explaining why nothing is drawn right now.
      */}
      {indicatorsQuery.isSuccess && hasPoints && analysisQuery.isSuccess && divergence && (
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

      {/*
        Divergence-marker click-to-explain balloon (frontend-divergence-
        markers) -- same pattern/content source as `PriceChart.tsx`'s own.
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
