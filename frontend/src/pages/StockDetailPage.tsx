import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useParams } from 'react-router-dom'
import ErrorState from '../components/common/ErrorState/ErrorState'
import LoadingState from '../components/common/LoadingState/LoadingState'
import PageHeader from '../components/common/PageHeader/PageHeader'
import IndicatorsPanel from '../features/stocks/components/IndicatorsPanel'
import PriceChart from '../features/stocks/components/PriceChart'
import ScreensPanel from '../features/stocks/components/ScreensPanel'
import SignalSummary from '../features/stocks/components/SignalSummary'
import TickerSearchBox from '../features/stocks/components/TickerSearchBox'
import { useStockAnalysis } from '../features/stocks/hooks/useStockAnalysis'

/**
 * Stock analysis page: `GET /api/stocks/{ticker}/analysis`'s Triple Screen
 * signal, confidence, per-screen detail, and latest indicator values for one
 * ticker (docs/Analyse.md §6, docs/architecture/API.md), plus the raw OHLCV
 * candlestick chart from `GET /.../history` (PriceChart, frontend-stock-history-chart).
 * Stays thin per Frontend.md §3 — all fetching lives in useStockAnalysis/
 * useStockHistory, all domain rendering lives in
 * SignalSummary/ScreensPanel/IndicatorsPanel/PriceChart.
 *
 * Renders TickerSearchBox (the same entry point built by
 * frontend-dashboard-page) in its own PageHeader action, so switching to a
 * different ticker doesn't require navigating back to the Dashboard first —
 * see this task's `decisions` entry for why this reuses rather than
 * duplicates that component.
 */
export default function StockDetailPage() {
  const { ticker = '' } = useParams<{ ticker: string }>()
  const analysisQuery = useStockAnalysis(ticker)

  return (
    <>
      <PageHeader title={ticker || 'Stock Detail'} action={<TickerSearchBox />} />

      {analysisQuery.isLoading && (
        <LoadingState message={`Loading analysis for ${ticker}...`} />
      )}
      {analysisQuery.isError && <ErrorState error={analysisQuery.error} />}

      {analysisQuery.data && (
        <Stack spacing={3}>
          <Typography variant="body2" color="text.secondary">
            As of {analysisQuery.data.as_of}
          </Typography>

          <SignalSummary
            signal={analysisQuery.data.signal}
            confidence={analysisQuery.data.confidence}
            confidenceBreakdown={analysisQuery.data.confidence_breakdown}
          />

          <ScreensPanel screens={analysisQuery.data.screens} />

          <IndicatorsPanel indicators={analysisQuery.data.indicators} />

          <PriceChart ticker={ticker} />
        </Stack>
      )}
    </>
  )
}
