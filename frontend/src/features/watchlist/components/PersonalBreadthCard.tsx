import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import EmptyState from '../../../components/common/EmptyState/EmptyState'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import StatCard from '../../../components/common/StatCard/StatCard'
import { useWatchlistBreadth } from '../hooks/useWatchlistBreadth'
import { personalBreadthHelp } from './personalBreadthHelp'

/**
 * Watchlist-page widget surfacing `GET /api/watchlist/breadth`
 * (docs/architecture/API.md#get-apiwatchlistbreadth, docs/Analyse.md's
 * "Personal breadth proxy" section, backend-watchlist-breadth-proxy): a
 * BULLISH/BEARISH/NEUTRAL Screen 1 (Tide) trend breakdown across the union
 * of the watchlist and portfolio tickers. Explicitly framed — in both the
 * heading and the `MetricHelp` balloon (`personalBreadthHelp.ts`) — as a
 * *personal* approximation of true market breadth, not the real thing,
 * since it only ever reflects the tickers this particular user happens to
 * be tracking rather than a broad market universe (this task's
 * description; see this task's `decisions` entry for why that framing
 * lives in the heading text itself and not only in the help balloon).
 *
 * Feature component (not `common/`): every field it renders (a tracked
 * ticker, a Tide trend count) is a Triple Screen/watchlist domain concept,
 * and it owns its own `useWatchlistBreadth` call so `WatchlistPage` stays a
 * thin composition (Frontend.md §3) — same reasoning as
 * `features/portfolio/components/RiskSummaryCard.tsx`.
 */
export default function PersonalBreadthCard() {
  const breadthQuery = useWatchlistBreadth()

  if (!breadthQuery.data) {
    if (breadthQuery.isError) {
      return <ErrorState error={breadthQuery.error} />
    }
    return <LoadingState message="Loading personal breadth..." />
  }

  const data = breadthQuery.data
  const help = personalBreadthHelp(data)

  return (
    <Stack spacing={1}>
      <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
        <Typography variant="h6" component="h2">
          Personal Breadth (Watchlist + Portfolio)
        </Typography>
        <MetricHelp
          metricLabel={help.metricLabel}
          definition={help.definition}
          elderContext={help.elderContext}
          valueInterpretation={help.valueInterpretation}
        />
      </Stack>

      {data.tracked_ticker_count === 0 ? (
        <EmptyState message="Add a ticker to your watchlist or portfolio to see a personal breadth breakdown." />
      ) : (
        <>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <StatCard
              label="Bullish"
              value={`${data.bullish_count} (${data.bullish_pct.toFixed(1)}%)`}
            />
            <StatCard
              label="Bearish"
              value={`${data.bearish_count} (${data.bearish_pct.toFixed(1)}%)`}
            />
            <StatCard
              label="Neutral"
              value={`${data.neutral_count} (${data.neutral_pct.toFixed(1)}%)`}
            />
          </Stack>
          {data.unavailable_count > 0 && (
            <Typography variant="caption" color="text.secondary">
              {data.unavailable_count} of {data.tracked_ticker_count} tracked ticker
              {data.tracked_ticker_count === 1 ? '' : 's'} currently unavailable (excluded
              above).
            </Typography>
          )}
        </>
      )}
    </Stack>
  )
}
