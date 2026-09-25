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

  const ibkrAvailable = ibkrStatusQuery.data?.state === 'available'
  const preloadTooltip = ibkrStatusQuery.data
    ? (ibkrStatusQuery.data.detail ?? 'IBKR is not currently available.')
    : 'Checking IBKR availability…'

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
                  onClick={() => setPreloadDialogOpen(true)}
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
      />
      <IbkrPreloadDialog
        open={preloadDialogOpen}
        onClose={() => setPreloadDialogOpen(false)}
        existingPositions={portfolioQuery.data?.positions ?? []}
      />
    </>
  )
}
