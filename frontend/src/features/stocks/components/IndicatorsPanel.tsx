import Stack from '@mui/material/Stack'
import type { Indicators } from '../../../api/stocks'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import StatCard from '../../../components/common/StatCard/StatCard'
import { formatNullableNumber } from '../../../utils/format'
import {
  bearPowerHelp,
  bullPowerHelp,
  ema13Help,
  ema26Help,
  macdHistogramHelp,
} from './metricHelpContent'

export interface IndicatorsPanelProps {
  indicators: Indicators
}

// `Indicators`' fields are typed as non-optional `number` (backend/app/api/schemas.py).
// docs/tasks/api-stocks-analysis-nullable-indicators.json fixed the backend-side root
// cause (an unsettled latest daily bar with NaN OHLC is now excluded from analysis via
// `app.signals.engine.drop_malformed_daily_bars` rather than leaking a JSON `null` onto
// the wire), so this guard shouldn't be reachable against a real backend response
// anymore — kept as defense-in-depth (treating the generated type as optimistic, not a
// runtime guarantee) rather than removed, consistent with the nullable-price display
// pattern used elsewhere (e.g. PositionsTable.tsx's formatNullableCurrency). Uses the
// shared formatNullableNumber (utils/format.ts) with this panel's own two-decimal
// formatting convention, rather than ScreensPanel's independent copy of the same guard.
function formatValue(value: number | null | undefined): string {
  return formatNullableNumber(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/**
 * Latest-bar indicator values from `GET /api/stocks/{ticker}/analysis` as a
 * small stat grid (common/StatCard) — explicitly *not* a chart overlay, per
 * Frontend.md §5: the backend only returns indicator values for the latest
 * bar, not a historical series, so there is nothing to plot over time
 * without duplicating indicator math client-side (which Frontend.md §5
 * rules out). PriceChart.tsx (frontend-stock-history-chart) renders the
 * OHLCV candlesticks separately, with no indicator line drawn on it.
 *
 * Each StatCard gets a `common/MetricHelp` question-mark icon in its
 * top-right corner (`StatCard`'s `corner` slot) explaining what the
 * indicator is, how it fits Elder's methodology, and an interpretation of
 * this specific current value (`metricHelpContent.ts`,
 * frontend-stock-detail-metric-help) — e.g. EMA13/EMA26 read each other's
 * relationship (uptrend/downtrend), MACD Histogram reads its sign, and
 * Bull/Bear Power read whether buyers/sellers pushed price past EMA(13).
 */
export default function IndicatorsPanel({ indicators }: IndicatorsPanelProps) {
  return (
    <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap' }}>
      <StatCard
        label="EMA (13)"
        value={formatValue(indicators.ema_13)}
        corner={
          <MetricHelp
            metricLabel={ema13Help.metricLabel}
            definition={ema13Help.definition}
            elderContext={ema13Help.elderContext}
            valueInterpretation={ema13Help.interpretValue(indicators.ema_13, indicators.ema_26)}
          />
        }
      />
      <StatCard
        label="EMA (26)"
        value={formatValue(indicators.ema_26)}
        corner={
          <MetricHelp
            metricLabel={ema26Help.metricLabel}
            definition={ema26Help.definition}
            elderContext={ema26Help.elderContext}
            valueInterpretation={ema26Help.interpretValue(indicators.ema_26, indicators.ema_13)}
          />
        }
      />
      <StatCard
        label="MACD Histogram"
        value={formatValue(indicators.macd_histogram)}
        corner={
          <MetricHelp
            metricLabel={macdHistogramHelp.metricLabel}
            definition={macdHistogramHelp.definition}
            elderContext={macdHistogramHelp.elderContext}
            valueInterpretation={macdHistogramHelp.interpretValue(indicators.macd_histogram)}
          />
        }
      />
      <StatCard
        label="Bull Power"
        value={formatValue(indicators.bull_power)}
        corner={
          <MetricHelp
            metricLabel={bullPowerHelp.metricLabel}
            definition={bullPowerHelp.definition}
            elderContext={bullPowerHelp.elderContext}
            valueInterpretation={bullPowerHelp.interpretValue(indicators.bull_power)}
          />
        }
      />
      <StatCard
        label="Bear Power"
        value={formatValue(indicators.bear_power)}
        corner={
          <MetricHelp
            metricLabel={bearPowerHelp.metricLabel}
            definition={bearPowerHelp.definition}
            elderContext={bearPowerHelp.elderContext}
            valueInterpretation={bearPowerHelp.interpretValue(indicators.bear_power)}
          />
        }
      />
    </Stack>
  )
}
