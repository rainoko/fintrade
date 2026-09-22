import ErrorState from '../components/common/ErrorState/ErrorState'
import LoadingState from '../components/common/LoadingState/LoadingState'
import PageHeader from '../components/common/PageHeader/PageHeader'
import UnavailableState from '../components/common/UnavailableState/UnavailableState'
import ScannerPanel from '../features/scanner/components/ScannerPanel'
import { useScannerParams } from '../features/scanner/hooks/useScannerParams'

/**
 * Scanner page ('/scanner'): pick one of IBKR's own predefined scan
 * categories, run it, and review the resulting candidate list — a new,
 * standalone page per docs/ideas.md's ch. 56 scoping (distinct from the
 * watchlist and the ticker detail view; the natural flow is run a scan ->
 * review candidates -> add hits worth tracking to the watchlist -> drill
 * into each via the existing ticker detail view). Stays thin per
 * Frontend.md §3 — this page owns only `GET /api/ibkr/scanner/params`'s
 * query (the page-level availability gate, matching every other page's own
 * top-level query + loading/error/data split, e.g. WatchlistPage/
 * PortfolioPage) and its own loading/error/unavailable states; the actual
 * pick-a-category/run-a-scan/review-results/add-to-watchlist flow lives in
 * ScannerPanel/ScannerResultsTable.
 *
 * A non-'available' `state` (disabled/gateway_unreachable/not_authenticated)
 * renders the shared `common/UnavailableState` — a distinct, non-error
 * "nothing's wrong, it's just not usable right now" treatment from
 * `ErrorState`'s alert styling — matching the backend's own contract of
 * never treating "IBKR isn't connected" as a request failure (this task's
 * description).
 */
export default function ScannerPage() {
  const paramsQuery = useScannerParams()

  return (
    <>
      <PageHeader title="Scanner" />

      {paramsQuery.isLoading && <LoadingState message="Loading scan categories..." />}
      {paramsQuery.isError && <ErrorState error={paramsQuery.error} />}

      {paramsQuery.data && paramsQuery.data.state !== 'available' && (
        <UnavailableState
          heading="Scanner unavailable"
          message={
            paramsQuery.data.detail ?? 'The IBKR market scanner is not available right now.'
          }
        />
      )}

      {paramsQuery.data && paramsQuery.data.state === 'available' && (
        <ScannerPanel categories={paramsQuery.data.categories ?? []} />
      )}
    </>
  )
}
