import Stack from '@mui/material/Stack'
import { useState } from 'react'
import type { HistoryInterval } from '../../../api/stocks'
import OscillatorChart from './OscillatorChart'
import PriceChart, { DEFAULT_INTERVAL, DEFAULT_RANGE } from './PriceChart'
import TrendStrengthChart from './TrendStrengthChart'
import VolumeIndicatorsChart from './VolumeIndicatorsChart'

export interface StockChartsProps {
  ticker: string
}

/**
 * Composes the candlestick `PriceChart` (OHLCV + EMA13/EMA26 + BUY/SELL
 * signal overlay) with `OscillatorChart` (historical Stochastic %K/Force
 * Index/MACD Histogram), `VolumeIndicatorsChart` (historical OBV/A-D,
 * frontend-volume-indicators-chart), and `TrendStrengthChart` (historical
 * +DI/-DI/ADX/ATR, frontend-trend-strength-chart) beneath it, keeping all
 * four panes on the exact same range/interval selection — the "separate
 * synced panel beneath the price chart" this task's description calls for.
 *
 * `PriceChart` still owns its own range/interval `ToggleButtonGroup`
 * controls and local state (unchanged — see its own doc comment); this
 * wrapper just mirrors every change it reports via the optional
 * `onRangeChange`/`onIntervalChange` props into its own state, then passes
 * that mirrored `range` (and `interval === 'daily'` as `enabled`) into
 * `OscillatorChart`. Both start from the exact same `DEFAULT_RANGE`/
 * `DEFAULT_INTERVAL` constants `PriceChart` itself uses, so the two panes
 * are already in sync on first render, before any user interaction.
 *
 * Decision (this task's `decisions` entry): a mirrored-callback pattern
 * rather than converting `PriceChart` into a fully controlled component
 * (range/interval state and its selector UI lifted entirely out of it) —
 * the callback mirror is a small, additive change to a component with a
 * recent crash history (frontend-chart-signal-overlay, PR #107) and leaves
 * its existing effect bodies/cleanup-ordering logic completely untouched,
 * whereas lifting its state would have meant either duplicating the
 * range/interval selector UI in this wrapper or reworking `PriceChart`'s
 * props into an uncontrolled/controlled dual-mode component for no benefit
 * beyond this one new consumer.
 *
 * Passes `errorSurfacedBySibling` to `OscillatorChart`/`VolumeIndicatorsChart`/
 * `TrendStrengthChart` (frontend-position-risk-columns-followups-followups-
 * followups-followups) since `PriceChart`, mounted first here, already owns
 * the `GET /api/stocks/{ticker}/indicators` failure's ErrorState — see each
 * of those components' own `errorSurfacedBySibling` prop doc comment for why
 * this is an explicit opt-in passed at the composition site rather than an
 * implicit assumption baked into each component.
 *
 * Feature composition component, not `common/`: it wires together two
 * ticker/indicator-specific charts, not a generic layout primitive.
 */
export default function StockCharts({ ticker }: StockChartsProps) {
  const [range, setRange] = useState<string>(DEFAULT_RANGE)
  const [interval, setInterval] = useState<HistoryInterval>(DEFAULT_INTERVAL)

  return (
    <Stack spacing={3}>
      <PriceChart
        ticker={ticker}
        onRangeChange={setRange}
        onIntervalChange={setInterval}
      />
      <OscillatorChart
        ticker={ticker}
        range={range}
        enabled={interval === 'daily'}
        errorSurfacedBySibling
      />
      <VolumeIndicatorsChart
        ticker={ticker}
        range={range}
        enabled={interval === 'daily'}
        errorSurfacedBySibling
      />
      <TrendStrengthChart
        ticker={ticker}
        range={range}
        enabled={interval === 'daily'}
        errorSurfacedBySibling
      />
    </Stack>
  )
}
