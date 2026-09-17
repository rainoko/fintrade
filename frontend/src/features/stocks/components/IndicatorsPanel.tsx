import Stack from '@mui/material/Stack'
import type { Indicators } from '../../../api/stocks'
import StatCard from '../../../components/common/StatCard/StatCard'

export interface IndicatorsPanelProps {
  indicators: Indicators
}

// `Indicators`' fields are typed as non-optional `number` (backend/app/api/schemas.py),
// but an unsettled latest daily bar (NaN OHLC from the market data provider) makes the
// backend serialize these as JSON `null` on the wire despite the schema — see
// docs/tasks/api-stocks-analysis-nullable-indicators.json for the backend-side fix.
// Treat the generated type as optimistic, not a runtime guarantee, and fall back
// gracefully rather than crashing, consistent with the nullable-price display pattern
// used elsewhere (e.g. PositionsTable.tsx's formatNullableCurrency).
function formatValue(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '—'
  }
  return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/**
 * Latest-bar indicator values from `GET /api/stocks/{ticker}/analysis` as a
 * small stat grid (common/StatCard) — explicitly *not* a chart overlay, per
 * Frontend.md §5: the backend only returns indicator values for the latest
 * bar, not a historical series, so there is nothing to plot over time
 * without duplicating indicator math client-side (which Frontend.md §5
 * rules out). PriceChart.tsx (frontend-stock-history-chart) renders the
 * OHLCV candlesticks separately, with no indicator line drawn on it.
 */
export default function IndicatorsPanel({ indicators }: IndicatorsPanelProps) {
  return (
    <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap' }}>
      <StatCard label="EMA (13)" value={formatValue(indicators.ema_13)} />
      <StatCard label="EMA (26)" value={formatValue(indicators.ema_26)} />
      <StatCard label="MACD Histogram" value={formatValue(indicators.macd_histogram)} />
      <StatCard label="Bull Power" value={formatValue(indicators.bull_power)} />
      <StatCard label="Bear Power" value={formatValue(indicators.bear_power)} />
    </Stack>
  )
}
