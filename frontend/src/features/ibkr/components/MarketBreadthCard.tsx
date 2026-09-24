import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import EmptyState from '../../../components/common/EmptyState/EmptyState'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import IbkrStatusBadge, {
  type IbkrGatewayState,
} from '../../../components/common/IbkrStatusBadge/IbkrStatusBadge'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import StatCard from '../../../components/common/StatCard/StatCard'
import { formatNullableNumber, formatSignedSpread } from '../../../utils/format'
import { useMarketBreadth, type MarketBreadthData } from '../hooks/useMarketBreadth'
import { marketBreadthHelp } from './marketBreadthHelp'

/**
 * Both snapshots share one underlying `IBKRProvider`/gateway-availability
 * check server-side, so their `state` fields should normally agree —
 * `advance`'s is checked first, `decline`'s only as a fallback for the
 * unlikely case a session drops between the two sequential requests
 * `useMarketBreadth` makes.
 */
function resolveUnavailableState(data: MarketBreadthData): IbkrGatewayState | null {
  if (data.advance.state !== 'available') {
    return data.advance.state
  }
  if (data.decline.state !== 'available') {
    return data.decline.state
  }
  return null
}

/**
 * Explains why the 5-day/20-day spread StatCards below still read "—" —
 * `IBKRBreadthSnapshotResponse.rolling_5d`/`rolling_20d` are null until
 * `days_recorded` reaches 5/20 respectively (API.md), rather than a
 * misleadingly partial sum.
 */
function historyCaption(daysRecorded: number): string | null {
  if (daysRecorded >= 20) {
    return null
  }
  if (daysRecorded < 5) {
    return `${daysRecorded} of 5 days recorded so far — the 5-day spread appears once 5 days are recorded (20 for the 20-day spread).`
  }
  return `${daysRecorded} of 20 days recorded so far — the 20-day spread appears once 20 days are recorded.`
}

/**
 * Watchlist-page widget surfacing `POST /api/ibkr/breadth/snapshot` x2
 * (`useMarketBreadth`) — Elder ch. 34-36's real, broad-market breadth
 * indicators, approximated via the IBKR scanner (docs/Analyse.md's
 * "IBKR-scanner breadth approximation" section, `backend-market-breadth-
 * indicators`). Deliberately distinct — a different heading, a different
 * `MetricHelp` explanation, and its own disabled/unavailable presentation
 * (`common/IbkrStatusBadge`, the same chip `IbkrStatusIndicator` uses) —
 * from `features/watchlist/components/PersonalBreadthCard` so a user
 * doesn't mistake one for the other: this widget approximates the *whole*
 * market via IBKR, `PersonalBreadthCard` only ever reflects the tickers
 * this particular user happens to be tracking. See this task's `decisions`
 * entry.
 *
 * Feature component (not `common/`): every field it renders is an
 * IBKR-scanner/Elder-breadth domain concept, and it owns its own
 * `useMarketBreadth` fetch/loading/error/unavailable-state handling so
 * `WatchlistPage` stays a thin composition (Frontend.md §3) — same
 * reasoning as `PersonalBreadthCard`/`features/ibkr/components/
 * IbkrStatusIndicator`. Lives under `features/ibkr/` (not
 * `features/watchlist/`) since every value it renders and the hook backing
 * it are IBKR-scanner domain concepts, not watchlist ones — `WatchlistPage`
 * imports it directly, the same way `AppShell` already imports
 * `IbkrStatusIndicator` from this same feature folder despite living
 * outside it.
 */
export default function MarketBreadthCard() {
  const breadthQuery = useMarketBreadth()

  if (!breadthQuery.data) {
    if (breadthQuery.isError) {
      return <ErrorState error={breadthQuery.error} />
    }
    return <LoadingState message="Loading market breadth..." />
  }

  const data = breadthQuery.data
  const unavailableState = resolveUnavailableState(data)
  const help = marketBreadthHelp(unavailableState ? null : data)
  const caption = unavailableState
    ? null
    : historyCaption(Math.min(data.advance.days_recorded, data.decline.days_recorded))

  return (
    <Stack spacing={1}>
      <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
        <Typography variant="h6" component="h2">
          Market Breadth (IBKR, Whole Market)
        </Typography>
        <MetricHelp
          metricLabel={help.metricLabel}
          definition={help.definition}
          elderContext={help.elderContext}
          valueInterpretation={help.valueInterpretation}
        />
      </Stack>

      {unavailableState ? (
        <EmptyState
          message="Real market breadth isn't available right now — it needs the optional IBKR Client Portal Gateway integration connected."
          action={
            <IbkrStatusBadge
              state={unavailableState}
              detail={data.advance.detail ?? data.decline.detail}
            />
          }
        />
      ) : (
        <>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <StatCard label="Top % Gainers (today)" value={formatNullableNumber(data.advance.count)} />
            <StatCard label="Top % Losers (today)" value={formatNullableNumber(data.decline.count)} />
            <StatCard
              label="Spread (5d)"
              value={formatSignedSpread(data.advance.rolling_5d, data.decline.rolling_5d, '—')}
            />
            <StatCard
              label="Spread (20d)"
              value={formatSignedSpread(data.advance.rolling_20d, data.decline.rolling_20d, '—')}
            />
          </Stack>
          {caption && (
            <Typography variant="caption" color="text.secondary">
              {caption}
            </Typography>
          )}
        </>
      )}
    </Stack>
  )
}
