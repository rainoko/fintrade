import Stack from '@mui/material/Stack'
import ErrorState from '../components/common/ErrorState/ErrorState'
import LoadingState from '../components/common/LoadingState/LoadingState'
import PageHeader from '../components/common/PageHeader/PageHeader'
import CftcCotCard from '../features/cftc/components/CftcCotCard'
import MarketBreadthCard from '../features/ibkr/components/MarketBreadthCard'
import AddTickerForm from '../features/watchlist/components/AddTickerForm'
import PersonalBreadthCard from '../features/watchlist/components/PersonalBreadthCard'
import WatchlistTable from '../features/watchlist/components/WatchlistTable'
import { useWatchlist } from '../features/watchlist/hooks/useWatchlist'

/**
 * Watchlist page ('/watchlist'): every watched ticker plus its current
 * BUY/SELL/HOLD signal (GET /api/watchlist), an add-ticker control, a
 * remove action per row, the "personal breadth" proxy widget
 * (PersonalBreadthCard, GET /api/watchlist/breadth,
 * frontend-breadth-widget), the real, IBKR-scanner-based market breadth
 * widget (MarketBreadthCard, POST /api/ibkr/breadth/snapshot,
 * frontend-market-breadth-widget), and the CFTC Commitments of Traders
 * widget (CftcCotCard, GET /api/cftc/cot, frontend-cftc-cot-display). Stays
 * thin per Frontend.md §3 — all fetching lives in
 * useWatchlist/useWatchlistBreadth/useMarketBreadth/useCftcCot/
 * useAddWatchlistItem/useRemoveWatchlistItem, all domain rendering lives in
 * WatchlistTable/AddTickerForm/PersonalBreadthCard/MarketBreadthCard/
 * CftcCotCard.
 *
 * PersonalBreadthCard/MarketBreadthCard/CftcCotCard are rendered
 * unconditionally alongside the watchlist table's own loading/error/data
 * states (not gated behind `watchlistQuery.data`) since each owns its own
 * independent fetch/loading/error handling and none's denominator is this
 * page's own watchlist query alone — see PersonalBreadthCard's own task
 * `decisions` entry for why the pattern was established, and
 * frontend-market-breadth-widget's `decisions` entry for why
 * MarketBreadthCard is placed directly below it (both are "breadth" widgets
 * a user might otherwise confuse for one another). CftcCotCard is placed
 * last — it's "whole futures market" context like MarketBreadthCard, but a
 * genuinely separate data source/methodology (CFTC positioning vs. IBKR
 * scanner-derived breadth), not a third breadth-style widget to stack
 * directly alongside the other two — see this task's `decisions` entry.
 */
export default function WatchlistPage() {
  const watchlistQuery = useWatchlist()

  return (
    <>
      <PageHeader title="Watchlist" action={<AddTickerForm />} />

      <Stack spacing={3}>
        <PersonalBreadthCard />
        <MarketBreadthCard />
        <CftcCotCard />

        {watchlistQuery.isLoading && <LoadingState message="Loading watchlist..." />}
        {watchlistQuery.isError && <ErrorState error={watchlistQuery.error} />}
        {watchlistQuery.data && <WatchlistTable items={watchlistQuery.data.items} />}
      </Stack>
    </>
  )
}
