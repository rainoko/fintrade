import ErrorState from '../components/common/ErrorState/ErrorState'
import LoadingState from '../components/common/LoadingState/LoadingState'
import PageHeader from '../components/common/PageHeader/PageHeader'
import AddTickerForm from '../features/watchlist/components/AddTickerForm'
import WatchlistTable from '../features/watchlist/components/WatchlistTable'
import { useWatchlist } from '../features/watchlist/hooks/useWatchlist'

/**
 * Watchlist page ('/watchlist'): every watched ticker plus its current
 * BUY/SELL/HOLD signal (GET /api/watchlist), an add-ticker control, and a
 * remove action per row. Stays thin per Frontend.md §3 — all fetching lives
 * in useWatchlist/useAddWatchlistItem/useRemoveWatchlistItem, all domain
 * rendering lives in WatchlistTable/AddTickerForm.
 */
export default function WatchlistPage() {
  const watchlistQuery = useWatchlist()

  return (
    <>
      <PageHeader title="Watchlist" action={<AddTickerForm />} />

      {watchlistQuery.isLoading && <LoadingState message="Loading watchlist..." />}
      {watchlistQuery.isError && <ErrorState error={watchlistQuery.error} />}

      {watchlistQuery.data && <WatchlistTable items={watchlistQuery.data.items} />}
    </>
  )
}
