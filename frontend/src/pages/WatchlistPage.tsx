import Stack from '@mui/material/Stack'
import ErrorState from '../components/common/ErrorState/ErrorState'
import LoadingState from '../components/common/LoadingState/LoadingState'
import PageHeader from '../components/common/PageHeader/PageHeader'
import AddTickerForm from '../features/watchlist/components/AddTickerForm'
import PersonalBreadthCard from '../features/watchlist/components/PersonalBreadthCard'
import WatchlistTable from '../features/watchlist/components/WatchlistTable'
import { useWatchlist } from '../features/watchlist/hooks/useWatchlist'

/**
 * Watchlist page ('/watchlist'): every watched ticker plus its current
 * BUY/SELL/HOLD signal (GET /api/watchlist), an add-ticker control, a
 * remove action per row, and the "personal breadth" proxy widget
 * (PersonalBreadthCard, GET /api/watchlist/breadth,
 * frontend-breadth-widget). Stays thin per Frontend.md §3 — all fetching
 * lives in useWatchlist/useWatchlistBreadth/useAddWatchlistItem/
 * useRemoveWatchlistItem, all domain rendering lives in
 * WatchlistTable/AddTickerForm/PersonalBreadthCard.
 *
 * PersonalBreadthCard is rendered unconditionally alongside the watchlist
 * table's own loading/error/data states (not gated behind
 * `watchlistQuery.data`) since it owns its own independent
 * `useWatchlistBreadth` fetch/loading/error handling and its denominator
 * spans the portfolio too, not just this page's own watchlist query — see
 * this task's `decisions` entry for why it sits above the table rather than
 * inside it.
 */
export default function WatchlistPage() {
  const watchlistQuery = useWatchlist()

  return (
    <>
      <PageHeader title="Watchlist" action={<AddTickerForm />} />

      <Stack spacing={3}>
        <PersonalBreadthCard />

        {watchlistQuery.isLoading && <LoadingState message="Loading watchlist..." />}
        {watchlistQuery.isError && <ErrorState error={watchlistQuery.error} />}
        {watchlistQuery.data && <WatchlistTable items={watchlistQuery.data.items} />}
      </Stack>
    </>
  )
}
