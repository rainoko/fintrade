import AddIcon from '@mui/icons-material/Add'
import CloudDownloadOutlinedIcon from '@mui/icons-material/CloudDownloadOutlined'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import Tooltip from '@mui/material/Tooltip'
import { useMemo, useState } from 'react'
import ErrorState from '../components/common/ErrorState/ErrorState'
import LoadingState from '../components/common/LoadingState/LoadingState'
import PageHeader from '../components/common/PageHeader/PageHeader'
import StatCard from '../components/common/StatCard/StatCard'
import { useIbkrStatus } from '../features/ibkr/hooks/useIbkrStatus'
import AddPositionDialog from '../features/portfolio/components/AddPositionDialog'
import IbkrPreloadDialog from '../features/portfolio/components/IbkrPreloadDialog'
import PositionsTable from '../features/portfolio/components/PositionsTable'
import RiskPanel from '../features/portfolio/components/RiskPanel'
import TradeFollowUpDuePanel from '../features/portfolio/components/TradeFollowUpDuePanel'
import TradeJournalPanel from '../features/portfolio/components/TradeJournalPanel'
import { usePortfolio } from '../features/portfolio/hooks/usePortfolio'
import { formatCurrency } from '../utils/format'

/**
 * Portfolio page: GET /api/portfolio's equity summary + positions table, and
 * the entry point for adding a position. Stays thin per Frontend.md §3 — all
 * fetching lives in usePortfolio/useAddPosition/useDeletePosition, all
 * domain rendering lives in PositionsTable/AddPositionDialog.
 *
 * The "Preload from IBKR" action (frontend-ibkr-portfolio-preload) is gated
 * on `GET /api/ibkr/status` reporting `state: 'available'`, reusing the same
 * `useIbkrStatus` hook `IbkrStatusIndicator` already calls for this exact
 * endpoint, rather than a second status query. Decision: the button always
 * renders (not hidden entirely when unavailable, unlike ScannerPage's own
 * whole-page `UnavailableState` swap for its own IBKR-dependent content) —
 * disabled with an explanatory tooltip instead, since this is one action
 * among several on an otherwise-always-usable page, and hiding it outright
 * would make a returning user wonder whether the feature was ever built at
 * all rather than understanding it's just not connected right now. See this
 * task's `decisions` entry.
 */
export default function PortfolioPage() {
  const portfolioQuery = usePortfolio()
  const ibkrStatusQuery = useIbkrStatus()
  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [preloadDialogOpen, setPreloadDialogOpen] = useState(false)

  const existingTickers = useMemo(
    () => portfolioQuery.data?.positions.map((position) => position.ticker) ?? [],
    [portfolioQuery.data],
  )

  // Distinct `strategy` values across the user's own currently-held
  // positions -- "recent tags" `Autocomplete` suggestions for
  // AddPositionDialog's own Strategy field (frontend-trade-strategy-tagging's
  // checklist item 4). Deliberately scoped to `usePortfolio()`'s own
  // already-fetched data (the same query this page already calls for
  // `existingTickers` above) rather than also reading
  // `GET /api/portfolio/closed-trades`: an earlier revision of this task
  // called `useClosedTrades()` directly here too to union in closed trades'
  // own strategy tags, but that kicks off that fetch at this page's own
  // mount instead of only once TradeJournalPanel itself mounts further down
  // -- shifting several *other*, timing-sensitive tests' assumptions about
  // render/query-resolution order on this same page (e.g. a position link
  // appearing in both PositionsTable and RiskPanel by the time a prior
  // assertion expected only one to have resolved yet). Scoping to held
  // positions only avoids that blast radius entirely, at the cost of not
  // suggesting a strategy only ever used on a now-closed trade -- see this
  // task's `decisions` entry for the full rationale, including why a
  // starker alternative (passing a callback down for AddPositionDialog to
  // pull the closed-trades list itself only once opened) was also
  // considered and rejected as more complex for the same marginal benefit.
  const recentStrategies = useMemo(() => {
    const strategies = (portfolioQuery.data?.positions ?? [])
      .map((position) => position.strategy)
      .filter((strategy): strategy is string => Boolean(strategy))
    return [...new Set(strategies)]
  }, [portfolioQuery.data])

  const ibkrAvailable = ibkrStatusQuery.data?.state === 'available'
  // `isError` is checked before `!data`, mirroring `IbkrStatusIndicator`'s
  // own check on this exact query (useIbkrStatus.ts's own docstring): a
  // genuine transport failure (this app's backend unreachable) must never
  // be mistaken for "still loading" -- without this, a backend-unreachable
  // state would leave this tooltip reading "Checking IBKR availability…"
  // forever, even though the button itself already stays correctly disabled
  // either way (`ibkrAvailable` is false whenever `data` is undefined).
  const preloadTooltip = ibkrStatusQuery.isError
    ? ibkrStatusQuery.error.detail
    : ibkrStatusQuery.data
      ? (ibkrStatusQuery.data.detail ?? 'IBKR is not currently available.')
      : 'Checking IBKR availability…'

  // `usePortfolio()` uses this app's global 60s `staleTime` (main.tsx), while
  // `IbkrPreloadDialog`'s own preview query deliberately uses `staleTime: 0`
  // (useIbkrPortfolioPreview.ts) for a fresh read every time it opens. Without
  // this, a ticker added/removed locally in the last 60s that hasn't yet
  // reappeared in `usePortfolio()`'s cache could render as "Not found
  // locally" in the dialog's conflict table (no checkbox, so it couldn't be
  // selected for deletion) even though the fresh preview correctly flags it
  // as conflicting. Refetching (not just invalidating) right when the dialog
  // opens closes that window entirely rather than only degrading gracefully
  // through it. See this task's `decisions` entry.
  const handleOpenPreloadDialog = () => {
    void portfolioQuery.refetch()
    setPreloadDialogOpen(true)
  }

  return (
    <>
      <PageHeader
        title="Portfolio"
        action={
          <Stack direction="row" spacing={1}>
            <Tooltip title={ibkrAvailable ? '' : preloadTooltip}>
              <span>
                <Button
                  variant="outlined"
                  startIcon={<CloudDownloadOutlinedIcon />}
                  onClick={handleOpenPreloadDialog}
                  disabled={!ibkrAvailable}
                >
                  Preload from IBKR
                </Button>
              </span>
            </Tooltip>
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={() => setAddDialogOpen(true)}
            >
              Add Position
            </Button>
          </Stack>
        }
      />

      {portfolioQuery.isLoading && <LoadingState message="Loading portfolio..." />}
      {portfolioQuery.isError && <ErrorState error={portfolioQuery.error} />}

      {portfolioQuery.data && (
        <Stack spacing={3}>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <StatCard
              label="Cash"
              value={formatCurrency(portfolioQuery.data.equity.cash)}
            />
            <StatCard
              label="Positions Value"
              value={formatCurrency(portfolioQuery.data.equity.positions_value)}
            />
            <StatCard
              label="Total Equity"
              value={formatCurrency(portfolioQuery.data.equity.total)}
            />
          </Stack>
          <PositionsTable positions={portfolioQuery.data.positions} />
          <RiskPanel positions={portfolioQuery.data.positions} />
          <TradeFollowUpDuePanel />
          <TradeJournalPanel />
        </Stack>
      )}

      <AddPositionDialog
        open={addDialogOpen}
        onClose={() => setAddDialogOpen(false)}
        existingTickers={existingTickers}
        recentStrategies={recentStrategies}
      />
      <IbkrPreloadDialog
        open={preloadDialogOpen}
        onClose={() => setPreloadDialogOpen(false)}
        existingPositions={portfolioQuery.data?.positions ?? []}
      />
    </>
  )
}
