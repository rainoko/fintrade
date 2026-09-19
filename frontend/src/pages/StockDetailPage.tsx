import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useParams } from 'react-router-dom'
import ErrorState from '../components/common/ErrorState/ErrorState'
import LoadingState from '../components/common/LoadingState/LoadingState'
import PageHeader from '../components/common/PageHeader/PageHeader'
import IndicatorsPanel from '../features/stocks/components/IndicatorsPanel'
import ScreensPanel from '../features/stocks/components/ScreensPanel'
import SignalSummary from '../features/stocks/components/SignalSummary'
import StockCharts from '../features/stocks/components/StockCharts'
import TickerSearchBox from '../features/stocks/components/TickerSearchBox'
import { useStockAnalysis } from '../features/stocks/hooks/useStockAnalysis'

/**
 * Stock analysis page: `GET /api/stocks/{ticker}/analysis`'s Triple Screen
 * signal, confidence, per-screen detail, and latest indicator values for one
 * ticker (docs/Analyse.md §6, docs/architecture/API.md), plus the raw OHLCV
 * candlestick chart from `GET /.../history` and the historical indicator/
 * oscillator series from `GET /.../indicators` (`StockCharts`, composing
 * `PriceChart` + `OscillatorChart` — frontend-stock-history-chart,
 * frontend-chart-signal-overlay, frontend-oscillator-chart).
 * Stays thin per Frontend.md §3 — all fetching lives in useStockAnalysis/
 * useStockHistory/useIndicatorHistory, all domain rendering lives in
 * SignalSummary/ScreensPanel/IndicatorsPanel/StockCharts.
 *
 * Renders TickerSearchBox (the same entry point built by
 * frontend-dashboard-page) in its own PageHeader action, so switching to a
 * different ticker doesn't require navigating back to the Dashboard first —
 * see this task's `decisions` entry for why this reuses rather than
 * duplicates that component.
 */
export default function StockDetailPage() {
  const { ticker: rawTicker = '' } = useParams<{ ticker: string }>()
  // Normalize the URL param the same way TickerSearchBox normalizes it
  // before navigating (trim + uppercase) so a hand-typed/bookmarked/
  // externally-linked lowercase URL (e.g. /stocks/aapl) addresses the same
  // query-cache entry as a later /stocks/AAPL visit instead of triggering a
  // redundant refetch of identical data. The heading itself prefers the
  // backend-returned `ticker` once loaded (it's the authoritative casing),
  // falling back to this normalized value while loading/on error.
  const ticker = rawTicker.trim().toUpperCase()
  const analysisQuery = useStockAnalysis(ticker)
  const displayTicker = analysisQuery.data?.ticker ?? ticker

  return (
    <>
      <PageHeader title={displayTicker || 'Stock Detail'} action={<TickerSearchBox />} />

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
            confidenceBand={analysisQuery.data.confidence_band}
            confidenceBreakdown={analysisQuery.data.confidence_breakdown}
            screens={analysisQuery.data.screens}
          />

          <ScreensPanel
            screens={analysisQuery.data.screens}
            season={analysisQuery.data.indicators.season}
          />

          <IndicatorsPanel indicators={analysisQuery.data.indicators} />

          <StockCharts ticker={ticker} />
        </Stack>
      )}
    </>
  )
}
