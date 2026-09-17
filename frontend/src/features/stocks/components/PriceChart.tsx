import Box from '@mui/material/Box'
import Stack from '@mui/material/Stack'
import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import {
  CandlestickSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts'
import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react'
import type { HistoryInterval } from '../../../api/stocks'
import EmptyState from '../../../components/common/EmptyState/EmptyState'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
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
 * Candlestick price chart for `GET /api/stocks/{ticker}/history`, built on
 * TradingView Lightweight Charts. Owns its own range/interval selection as
 * local UI state (Frontend.md §2 — not server data, so plain `useState`
 * rather than lifted into the page or a shared store) and feeds it straight
 * into `useStockHistory`, which keys its query by both params so a change
 * always triggers a real refetch (see useStockHistory.ts).
 *
 * Renders raw OHLCV bars only — no indicator overlay — per Frontend.md §5:
 * the backend doesn't expose a historical indicator series, and recomputing
 * Elder's indicators in TypeScript would duplicate backend-only math.
 * `IndicatorsPanel` (fed by `/analysis`) is the latest-value counterpart
 * shown alongside this chart, not plotted on it.
 */
export default function PriceChart({ ticker }: PriceChartProps) {
  const [range, setRange] = useState<string>(DEFAULT_RANGE)
  const [interval, setInterval] = useState<HistoryInterval>(DEFAULT_INTERVAL)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)

  const historyQuery = useStockHistory(ticker, { range, interval })
  const bars = historyQuery.data?.bars ?? []
  const hasBars = bars.length > 0

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
    if (!container || !data || data.bars.length === 0) {
      return
    }

    const chart = createChart(container, {
      autoSize: true,
      layout: { background: { color: 'transparent' } },
    })
    const series = chart.addSeries(CandlestickSeries)
    series.setData(
      data.bars.map((bar) => ({
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
    </Stack>
  )
}
