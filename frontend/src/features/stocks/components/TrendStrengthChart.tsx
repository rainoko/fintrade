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
import { adxHelp, atrHelp, directionalSystemHelp } from './metricHelpContent'

export interface TrendStrengthChartProps {
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
  /**
   * Set by a caller that already renders another component surfacing the
   * exact same `GET /api/stocks/{ticker}/indicators` failure (today:
   * `StockCharts` passes `true` because `PriceChart`, mounted alongside this
   * chart, already owns this shared failure's ErrorState — both components
   * share the identical `useIndicatorHistory` hook/query key, so rendering a
   * second `ErrorState` here would just duplicate the first one). Defaults
   * to `false`, so a standalone mount of this chart (no such sibling, e.g. a
   * future page or Storybook story) still surfaces a real fetch failure
   * instead of silently rendering nothing.
   *
   * Explicit, caller-supplied opt-in rather than an implicit "whichever
   * sibling happens to render first/already handles it" assumption — same
   * `errorSurfacedBySibling` contract `SellFlaggedPositionsCard`/
   * `OscillatorChart`/`VolumeIndicatorsChart` already establish (see any of
   * their own prop doc comments) and the same shape this task's own
   * checklist calls out: before this prop existed, this chart's suppression
   * of its own ErrorState was a hard-coded, unconditional assumption baked
   * into the component that `PriceChart` is always mounted as a sibling,
   * which nothing structurally enforced (see this task's `decisions` entry,
   * frontend-position-risk-columns-followups-followups-followups-followups).
   */
  errorSurfacedBySibling?: boolean
}

const CHART_HEIGHT = 420

/**
 * `trend_strength.{atr,plus_di,minus_di,adx}` are each independently
 * nullable `float | None` on the generated `TrendStrength` type
 * (backend/app/api/schemas.py) — `atr`/`plus_di`/`minus_di` finish their
 * 13-bar warm-up together, `adx` needs a further 13-bar window of `DX` on
 * top of that, so it stays null well after the other three go finite (see
 * the backend-indicator-atr-adx task's own decisions entry). `trend_strength`
 * itself is typed as always-present (never null/undefined) on
 * `IndicatorHistoryPoint`, but is still accessed via `?.` here for
 * defense-in-depth — the same "an honestly-typed field is not a runtime
 * guarantee" posture `OscillatorChart.tsx`'s own `isFiniteValue` doc comment
 * documents, extended one level deeper since this is the first per-point
 * *nested object* (rather than flat scalar field) this app's chart
 * components have projected from `/indicators`.
 */
const isFiniteValue = isFiniteNumber

interface TrendStrengthSeriesData {
  plusDi: { time: Time; value: number }[]
  minusDi: { time: Time; value: number }[]
  adx: { time: Time; value: number }[]
  atr: { time: Time; value: number }[]
}

/**
 * Projects `/indicators` points into the four trend-strength series this
 * pane plots, in a single pass — same convention as `OscillatorChart.tsx`'s
 * `buildOscillatorSeriesData`/`VolumeIndicatorsChart.tsx`'s
 * `buildVolumeIndicatorsSeriesData`. Each series is filtered independently
 * by `isFiniteValue` (a still-warming-up point is simply omitted from that
 * one series, not the whole pane) — `adx` in particular is routinely absent
 * for a long leading span of bars where `plus_di`/`minus_di`/`atr` are
 * already finite, per this component's own doc comment above.
 */
function buildTrendStrengthSeriesData(
  points: readonly IndicatorHistoryPoint[],
): TrendStrengthSeriesData {
  const plusDi: TrendStrengthSeriesData['plusDi'] = []
  const minusDi: TrendStrengthSeriesData['minusDi'] = []
  const adx: TrendStrengthSeriesData['adx'] = []
  const atr: TrendStrengthSeriesData['atr'] = []
  for (const point of points) {
    const time = point.date as Time
    const plusDiValue = point.trend_strength?.plus_di
    if (isFiniteValue(plusDiValue)) {
      plusDi.push({ time, value: plusDiValue })
    }
    const minusDiValue = point.trend_strength?.minus_di
    if (isFiniteValue(minusDiValue)) {
      minusDi.push({ time, value: minusDiValue })
    }
    const adxValue = point.trend_strength?.adx
    if (isFiniteValue(adxValue)) {
      adx.push({ time, value: adxValue })
    }
    const atrValue = point.trend_strength?.atr
    if (isFiniteValue(atrValue)) {
      atr.push({ time, value: atrValue })
    }
  }
  return { plusDi, minusDi, adx, atr }
}

/**
 * Historical Directional System / ADX / ATR pane (docs/Analyse.md §4 row
 * 16, Elder ch. 24), sourced from `GET /api/stocks/{ticker}/indicators` via
 * the shared `useIndicatorHistory` hook (same hook, same query-key
 * convention `PriceChart.tsx`/`OscillatorChart.tsx`/
 * `VolumeIndicatorsChart.tsx` already use — deduplicated by TanStack Query,
 * not fetched again, alongside those panes). No indicator math happens
 * here — every plotted value comes straight from the backend response, per
 * Frontend.md §5's "backend computes, frontend displays" rule.
 *
 * Decision (this task's `decisions` entry): a NEW dedicated chart
 * component, not a fifth/sixth/seventh/eighth series folded into
 * `OscillatorChart.tsx`. `OscillatorChart.tsx`'s own doc comment scopes it
 * explicitly to "historical oscillator pane for Screen 2 (the Wave)" — every
 * series already there is a Screen-2 input (Stochastic/RSI/Force Index) or
 * the Impulse System's slope input (MACD Histogram). +DI/-DI/ADX/ATR belong
 * to none of that: they're the Directional System (Elder ch. 24), a
 * different chapter's worth of trend-strength/volatility tooling, purely
 * informational and explicitly never read by `signal`/`confidence`
 * (docs/Analyse.md §4 row 16, the backend-indicator-atr-adx task's own scope
 * note) — the same "conceptually distinct, not a Wave input" reasoning
 * `frontend-volume-indicators-chart`'s own decision already applied to
 * OBV/A-D. A new component keeps that distinction visible to a user reading
 * the page rather than blurring it into an already-large, differently-scoped
 * component.
 *
 * Decision (this task's `decisions` entry): +DI/-DI/ADX share ONE pane
 * (pane 0) while ATR gets its OWN pane (pane 1) within the same chart
 * instance, rather than either three separate panes or one shared pane for
 * all four. +DI/-DI/ADX are constructed from the exact same smoothed
 * True-Range/+DM/-DM pipeline and land on the same roughly-0-100 scale
 * (`DX`/`ADX`'s own formula caps at 100; +DI/-DI are practically always well
 * under it), so plotting them together is the same "shared bound -> shared
 * pane" reasoning `OscillatorChart.tsx` already applies to Stochastic/RSI.
 * ATR is a fundamentally different kind of value — an unbounded volatility
 * measure in the ticker's own PRICE units, not a 0-100-ish percentage — so
 * sharing pane 0 with it would flatten +DI/-DI/ADX into a near-flat line
 * near zero on whatever scale ATR's much larger price-unit values force,
 * the same "different scale -> own pane" reasoning `OscillatorChart.tsx`
 * already applies to Force Index vs. MACD Histogram and
 * `VolumeIndicatorsChart.tsx` applies to OBV vs. A/D. ATR is not rendered as
 * bands around price on `PriceChart.tsx` (the task's other suggested
 * option): that would require computing and maintaining a mid-line/band
 * overlay on an already crash-history-sensitive component
 * (`StockCharts.tsx`'s own doc comment) for a feature (multi-ATR profit
 * targets/channel bands, docs/ideas.md) explicitly out of scope for this
 * task, whereas a simple line panel here is a small, additive, low-risk
 * change consistent with every other informational indicator this app
 * exposes as a line panel (OBV/A-D, Stochastic/RSI).
 *
 * No fixed reference lines (unlike Stochastic's 30/70 or Force
 * Index/MACD Histogram's zero baseline): neither docs/Analyse.md nor
 * docs/ideas.md gives ADX/+DI/-DI a documented numeric threshold the way it
 * does for those — Elder's own ADX rule is about its *slope* (rising vs.
 * falling) and its *rise off its own recent low* (the "rings a bell" rule),
 * not a fixed level, so a reference line here would be an invented
 * threshold with no textual support. That rule is instead stated explicitly,
 * and evaluated against this ticker's own current data, in `adxHelp`'s
 * `interpretValue` (per this task's own description).
 */
export default function TrendStrengthChart({
  ticker,
  range,
  enabled = true,
  errorSurfacedBySibling = false,
}: TrendStrengthChartProps) {
  const theme = useTheme()
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)

  const indicatorsQuery = useIndicatorHistory(ticker, { range }, { enabled })
  const points = indicatorsQuery.data?.points ?? []
  const hasPoints = points.length > 0
  const latestPoint = hasPoints ? points[points.length - 1] : undefined

  // Depends on `indicatorsQuery.data` itself (a new object per response)
  // rather than the `points`/`hasPoints` derived above, since those are
  // fresh references on every render regardless of whether the data
  // changed — same rationale as `OscillatorChart.tsx`'s/
  // `VolumeIndicatorsChart.tsx`'s own effect.
  useEffect(() => {
    const container = containerRef.current
    const data: IndicatorHistoryResponse | undefined = indicatorsQuery.data
    if (!container || !enabled || !data || data.points.length === 0) {
      return
    }

    const chart = createBaseChart(container)

    const { plusDi, minusDi, adx, atr } = buildTrendStrengthSeriesData(data.points)

    const plusDiSeries = chart.addSeries(
      LineSeries,
      {
        color: theme.palette.signal.buy,
        lineWidth: 2,
        title: '+DI (13)',
        priceLineVisible: false,
        lastValueVisible: false,
      },
      0,
    )
    plusDiSeries.setData(plusDi)

    const minusDiSeries = chart.addSeries(
      LineSeries,
      {
        color: theme.palette.signal.sell,
        lineWidth: 2,
        title: '-DI (13)',
        priceLineVisible: false,
        lastValueVisible: false,
      },
      0,
    )
    minusDiSeries.setData(minusDi)

    const adxSeries = chart.addSeries(
      LineSeries,
      {
        color: theme.palette.primary.main,
        lineWidth: 2,
        title: 'ADX (13)',
        priceLineVisible: false,
        lastValueVisible: false,
      },
      0,
    )
    adxSeries.setData(adx)

    const atrSeries = chart.addSeries(
      LineSeries,
      {
        color: theme.palette.secondary.main,
        lineWidth: 2,
        title: 'ATR (13)',
        priceLineVisible: false,
        lastValueVisible: false,
      },
      1,
    )
    atrSeries.setData(atr)

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
  // instead of silently disappearing, same convention
  // `OscillatorChart.tsx`/`VolumeIndicatorsChart.tsx` use for the exact same
  // reason.
  if (!enabled) {
    return (
      <EmptyState message="Trend strength indicators (+DI, -DI, ADX, ATR) are only available for the Daily interval." />
    )
  }

  return (
    <Stack spacing={1}>
      <Typography variant="subtitle2" color="text.secondary">
        Trend Strength (Informational)
      </Typography>

      {indicatorsQuery.isSuccess && hasPoints && (
        <Stack spacing={0.5}>
          <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
            <Box
              sx={{
                width: 14,
                height: 0,
                borderTop: '2px solid',
                borderColor: 'signal.buy',
              }}
            />
            <Box
              sx={{
                width: 14,
                height: 0,
                borderTop: '2px solid',
                borderColor: 'signal.sell',
              }}
            />
            <Typography variant="caption" color="text.secondary">
              +DI / -DI (13)
            </Typography>
            <MetricHelp
              metricLabel={directionalSystemHelp.metricLabel}
              definition={directionalSystemHelp.definition}
              elderContext={directionalSystemHelp.elderContext}
              valueInterpretation={directionalSystemHelp.interpretValue(
                latestPoint?.trend_strength?.plus_di,
                latestPoint?.trend_strength?.minus_di,
              )}
            />
          </Stack>
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
              ADX (13)
            </Typography>
            <MetricHelp
              metricLabel={adxHelp.metricLabel}
              definition={adxHelp.definition}
              elderContext={adxHelp.elderContext}
              valueInterpretation={adxHelp.interpretValue(points)}
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
              ATR (13)
            </Typography>
            <MetricHelp
              metricLabel={atrHelp.metricLabel}
              definition={atrHelp.definition}
              elderContext={atrHelp.elderContext}
              valueInterpretation={atrHelp.interpretValue(points)}
            />
          </Stack>
        </Stack>
      )}

      {indicatorsQuery.isLoading && (
        <LoadingState message={`Loading trend strength history for ${ticker}...`} />
      )}

      {/*
        common/ErrorState on indicatorsQuery.isError, UNLESS the caller
        passes errorSurfacedBySibling (see that prop's own doc comment).
        This chart shares the exact same useIndicatorHistory hook/query key
        with PriceChart, OscillatorChart, and VolumeIndicatorsChart (all
        composed together by StockCharts.tsx), so a single underlying
        GET /api/stocks/{ticker}/indicators failure would otherwise render
        four identical stacked alerts -- the same sibling-duplication shape
        already fixed on PortfolioPage (PR #258) and DashboardPage (PR #259).
        StockCharts.tsx passes errorSurfacedBySibling since PriceChart, its
        sibling here, already owns this failure's ErrorState; see this
        task's decisions entry
        (frontend-position-risk-columns-followups-followups-followups-
        followups).
      */}
      {!errorSurfacedBySibling && indicatorsQuery.isError && (
        <ErrorState error={indicatorsQuery.error} />
      )}

      {indicatorsQuery.isSuccess && !hasPoints && (
        <EmptyState message={`No trend strength history available for ${ticker}.`} />
      )}

      {indicatorsQuery.isSuccess && hasPoints && (
        <Box
          ref={containerRef}
          data-testid="trend-strength-chart-canvas"
          sx={{ width: '100%', height: CHART_HEIGHT }}
        />
      )}
    </Stack>
  )
}
