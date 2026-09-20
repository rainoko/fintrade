import Box from '@mui/material/Box'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'
import { LineSeries, type IChartApi, type Time } from 'lightweight-charts'
import { useEffect, useRef } from 'react'
import type { IndicatorHistoryPoint, IndicatorHistoryResponse } from '../../../api/stocks'
import EmptyState from '../../../components/common/EmptyState/EmptyState'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import { useIndicatorHistory } from '../hooks/useIndicatorHistory'
import { createBaseChart, isFiniteNumber } from '../../../utils/chart'
import { accumulationDistributionHelp, obvHelp } from './metricHelpContent'

export interface VolumeIndicatorsChartProps {
  ticker: string
  /** '<N>d' | '<N>w' | '<N>m' | '<N>y' | 'max' (see API.md) — kept in sync
   * with `PriceChart`'s own range selection by the shared `StockCharts`
   * wrapper, so every pane on the page always plots the same window. */
  range: string
  /**
   * `GET /api/stocks/{ticker}/indicators` has no `interval` param — every
   * value it returns is daily-cadence, same convention `OscillatorChart`'s
   * own `enabled` prop already documents. `StockCharts` passes
   * `interval === 'daily'` here. Defaults to `true` so this component works
   * standalone (e.g. in a test) without a caller needing to think about an
   * interval it may not otherwise track.
   */
  enabled?: boolean
}

const CHART_HEIGHT = 420

/**
 * `obv`/`accumulation_distribution` are declared plain, non-nullable
 * `number` on the generated `IndicatorHistoryPoint` type (unlike
 * `stochastic_k`/`rsi`/`force_index_2ema`, they have no warm-up window —
 * see the backend-indicator-obv-ad task's `decisions` entry for why both
 * series' first-bar/zero-range edge cases are mapped to a `0` contribution
 * rather than left `null`). This guard is still run for defense-in-depth,
 * same rationale `OscillatorChart.tsx`'s own `isFiniteValue` documents for
 * `macd_histogram` (also non-nullable): an honestly-typed field is not a
 * runtime guarantee, and Lightweight Charts' `setData` throws synchronously
 * on a non-numeric value, which — uncaught — crashes the whole app via the
 * root `AppErrorBoundary`, not just this pane.
 */
const isFiniteValue = isFiniteNumber

interface VolumeIndicatorSeriesData {
  obv: { time: Time; value: number }[]
  accumulationDistribution: { time: Time; value: number }[]
}

/**
 * Projects `/indicators` points into the two series this pane plots, in a
 * single pass — same convention as `OscillatorChart.tsx`'s
 * `buildOscillatorSeriesData`/`PriceChart.tsx`'s `buildOverlayData`. Each
 * series is filtered independently by `isFiniteValue`, though in practice
 * neither field is ever actually missing (see `isFiniteValue`'s own doc
 * comment above).
 */
function buildVolumeIndicatorsSeriesData(
  points: readonly IndicatorHistoryPoint[],
): VolumeIndicatorSeriesData {
  const obv: VolumeIndicatorSeriesData['obv'] = []
  const accumulationDistribution: VolumeIndicatorSeriesData['accumulationDistribution'] = []
  for (const point of points) {
    const time = point.date as Time
    if (isFiniteValue(point.obv)) {
      obv.push({ time, value: point.obv })
    }
    if (isFiniteValue(point.accumulation_distribution)) {
      accumulationDistribution.push({ time, value: point.accumulation_distribution })
    }
  }
  return { obv, accumulationDistribution }
}

/**
 * Historical volume-indicator pane: On-Balance Volume (OBV) and
 * Accumulation/Distribution (A/D) (docs/Analyse.md §4 rows 14-15, Elder
 * ch. 29), each sourced from `GET /api/stocks/{ticker}/indicators` via the
 * shared `useIndicatorHistory` hook (same hook, same query-key convention
 * `PriceChart.tsx`/`OscillatorChart.tsx` already use — deduplicated by
 * TanStack Query, not fetched a third time, alongside those two panes). No
 * indicator math happens here — every plotted value comes straight from the
 * backend response, per Frontend.md §5's "backend computes, frontend
 * displays" rule.
 *
 * Decision (this task's `decisions` entry): a NEW dedicated chart component,
 * not a fourth/fifth series folded into `OscillatorChart.tsx`. Every
 * existing series on that chart is a bounded-or-zero-centered Screen-2 (the
 * Wave) input — Stochastic/RSI are 0-100 bounded, Force Index/MACD
 * Histogram are unbounded but sign/zero-baseline-driven, and Force Index in
 * particular is the Wave's own oscillator field. OBV/A-D are neither: they
 * are unbounded *cumulative* running totals whose absolute level is
 * meaningless in isolation (depends entirely on how far back history
 * happens to start), they are purely informational (never read by
 * `signal`/`confidence` — docs/Analyse.md §4), and they don't belong to any
 * of the three Screens at all. Reusing `OscillatorChart.tsx`'s pane
 * machinery for a conceptually distinct "informational, not a Screen input"
 * category would blur that distinction for a user reading the page, and
 * `OscillatorChart.tsx`'s own doc comment already scopes it explicitly to
 * "historical oscillator pane for Screen 2." A new component is a small,
 * additive file rather than growing an already-large component (486 lines
 * before this task) with a fifth/sixth unrelated series.
 *
 * Decision (this task's `decisions` entry): OBV and A/D get their OWN
 * separate panes (0 and 1 respectively) rather than sharing one — unlike
 * Stochastic/RSI (which share a pane specifically because their shared
 * 0-100 bound makes direct comparison the whole point, per
 * frontend-rsi-oscillator-chart's own decision), OBV and A/D have no shared
 * bound: OBV sums a bar's *entire* volume to one side, while A/D sums only
 * the fraction of that volume implied by where the close landed in the
 * bar's range (at most the same magnitude, typically much smaller) — over a
 * long history the two series' absolute scales can diverge by an order of
 * magnitude or more, which would squash whichever one is smaller into a
 * flat line if forced onto one shared axis. Same "different scale -> own
 * pane" reasoning `OscillatorChart.tsx` already applies to Force Index vs.
 * MACD Histogram.
 *
 * No zero-baseline reference line on either pane (unlike Force Index/MACD
 * Histogram): both series are constructed to start at exactly 0 on the
 * first plotted bar (see the backend-indicator-obv-ad task's `decisions`
 * entry for the first-bar/zero-range edge-case rationale), so a "zero"
 * price line here would just mark the series' own arbitrary starting point,
 * not a meaningful sign-based threshold the way it does for Force
 * Index/MACD Histogram (whose sign is itself a buying/selling cue).
 *
 * No divergence overlay against OBV/A-D here — the backend-indicator-obv-ad
 * task explicitly scoped divergence detection against these two series to a
 * separate follow-up (it depends on `app.signals.swing_points`, computed
 * but not yet run against OBV/A-D); this component surfaces the raw series
 * only, per this task's own checklist.
 */
export default function VolumeIndicatorsChart({
  ticker,
  range,
  enabled = true,
}: VolumeIndicatorsChartProps) {
  const theme = useTheme()
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)

  const indicatorsQuery = useIndicatorHistory(ticker, { range }, { enabled })
  const points = indicatorsQuery.data?.points ?? []
  const hasPoints = points.length > 0

  // Depends on `indicatorsQuery.data` itself (a new object per response)
  // rather than the `points`/`hasPoints` derived above, since those are
  // fresh references on every render regardless of whether the data
  // changed — same rationale as `OscillatorChart.tsx`'s own effect.
  useEffect(() => {
    const container = containerRef.current
    const data: IndicatorHistoryResponse | undefined = indicatorsQuery.data
    if (!container || !enabled || !data || data.points.length === 0) {
      return
    }

    const chart = createBaseChart(container)

    const { obv, accumulationDistribution } = buildVolumeIndicatorsSeriesData(data.points)

    const obvSeries = chart.addSeries(
      LineSeries,
      {
        color: theme.palette.primary.main,
        lineWidth: 2,
        title: 'On-Balance Volume (OBV)',
        priceLineVisible: false,
        lastValueVisible: false,
      },
      0,
    )
    obvSeries.setData(obv)

    const adSeries = chart.addSeries(
      LineSeries,
      {
        color: theme.palette.secondary.main,
        lineWidth: 2,
        title: 'Accumulation/Distribution (A/D)',
        priceLineVisible: false,
        lastValueVisible: false,
      },
      1,
    )
    adSeries.setData(accumulationDistribution)

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
  // instead of silently disappearing, same convention `OscillatorChart.tsx`
  // uses for the exact same reason.
  if (!enabled) {
    return (
      <EmptyState message="Volume indicators (OBV, A/D) are only available for the Daily interval." />
    )
  }

  return (
    <Stack spacing={1}>
      <Typography variant="subtitle2" color="text.secondary">
        Volume Indicators (Informational)
      </Typography>

      {indicatorsQuery.isSuccess && hasPoints && (
        <Stack spacing={0.5}>
          <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
            <Box
              sx={{
                width: 14,
                height: 0,
                borderTop: '2px solid',
                borderColor: 'primary.main',
              }}
            />
            <Typography variant="caption" color="text.secondary">
              On-Balance Volume (OBV)
            </Typography>
            <MetricHelp
              metricLabel={obvHelp.metricLabel}
              definition={obvHelp.definition}
              elderContext={obvHelp.elderContext}
              valueInterpretation={obvHelp.interpretValue(points)}
            />
          </Stack>
          <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
            <Box
              sx={{
                width: 14,
                height: 0,
                borderTop: '2px solid',
                borderColor: 'secondary.main',
              }}
            />
            <Typography variant="caption" color="text.secondary">
              Accumulation/Distribution (A/D)
            </Typography>
            <MetricHelp
              metricLabel={accumulationDistributionHelp.metricLabel}
              definition={accumulationDistributionHelp.definition}
              elderContext={accumulationDistributionHelp.elderContext}
              valueInterpretation={accumulationDistributionHelp.interpretValue(points)}
            />
          </Stack>
        </Stack>
      )}

      {indicatorsQuery.isLoading && (
        <LoadingState message={`Loading volume indicator history for ${ticker}...`} />
      )}

      {indicatorsQuery.isError && <ErrorState error={indicatorsQuery.error} />}

      {indicatorsQuery.isSuccess && !hasPoints && (
        <EmptyState message={`No volume indicator history available for ${ticker}.`} />
      )}

      {indicatorsQuery.isSuccess && hasPoints && (
        <Box
          ref={containerRef}
          data-testid="volume-indicators-chart-canvas"
          sx={{ width: '100%', height: CHART_HEIGHT }}
        />
      )}
    </Stack>
  )
}
