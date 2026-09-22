import MenuBookIcon from '@mui/icons-material/MenuBook'
import Button from '@mui/material/Button'
import Link from '@mui/material/Link'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useState } from 'react'
import { Link as RouterLink, useParams } from 'react-router-dom'
import ErrorState from '../components/common/ErrorState/ErrorState'
import LoadingState from '../components/common/LoadingState/LoadingState'
import PageHeader from '../components/common/PageHeader/PageHeader'
import TradeApgarDialog from '../features/portfolio/components/TradeApgarDialog'
import FundamentalDataPanel from '../features/stocks/components/FundamentalDataPanel'
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
 * SignalSummary/FundamentalDataPanel/ScreensPanel/IndicatorsPanel/StockCharts.
 *
 * Renders TickerSearchBox (the same entry point built by
 * frontend-dashboard-page) in its own PageHeader action, so switching to a
 * different ticker doesn't require navigating back to the Dashboard first —
 * see this task's `decisions` entry for why this reuses rather than
 * duplicates that component.
 *
 * `FundamentalDataPanel` (earnings/dividend dates, short interest, insider
 * transactions and (frontend-insider-clusters-badge) detected
 * insider-transaction clusters — frontend-fundamental-data-panel) sits
 * directly below `SignalSummary`, ahead of `ScreensPanel`/`IndicatorsPanel`/
 * `StockCharts` — see that component's own doc comment for why (its
 * earnings-date warning banner needs to stay visible near the top of the
 * page, not buried below several other panels and the price chart).
 * `AnalysisResponse.insider_clusters` is passed straight through from this
 * page (it's a top-level sibling field to `extended_data`, not nested
 * inside it).
 *
 * A "Methodology reference" link to `/methodology`
 * (frontend-methodology-explainer) sits directly under the page header,
 * visible regardless of loading/error/data state — this is the page a user
 * is most likely to want the full Elder-methodology explainer from, since
 * every screen/indicator shown below is exactly what that page catalogs.
 *
 * A "Trade Apgar" button sits next to that link, opening `TradeApgarDialog`
 * (`frontend-trade-apgar`, ch. 58's pre-trade go/no-go check) for the
 * currently-viewed ticker. Placed here (ticker detail view) rather than a
 * dedicated page/route or an always-visible embedded panel — see this
 * task's `decisions` entry for the placement rationale. Only shown once
 * `analysisQuery.data` has loaded, since a genuinely unknown/errored ticker
 * has nothing meaningful to score.
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
  const [apgarTicker, setApgarTicker] = useState<string | null>(null)

  return (
    <>
      <PageHeader title={displayTicker || 'Stock Detail'} action={<TickerSearchBox />} />

      <Stack direction="row" spacing={2} sx={{ alignItems: 'center', mb: 3 }}>
        <Link
          component={RouterLink}
          to="/methodology"
          underline="hover"
          sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
        >
          <MenuBookIcon fontSize="small" />
          Methodology reference
        </Link>

        {analysisQuery.data && (
          <Button
            size="small"
            variant="outlined"
            onClick={() => setApgarTicker(displayTicker)}
          >
            Trade Apgar
          </Button>
        )}
      </Stack>

      <TradeApgarDialog ticker={apgarTicker} onClose={() => setApgarTicker(null)} />

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
            profitTarget={analysisQuery.data.profit_target}
          />

          <FundamentalDataPanel
            extendedData={analysisQuery.data.extended_data}
            insiderClusters={analysisQuery.data.insider_clusters}
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
