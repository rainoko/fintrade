import AddIcon from '@mui/icons-material/Add'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import { useMemo, useState } from 'react'
import ErrorState from '../components/common/ErrorState/ErrorState'
import LoadingState from '../components/common/LoadingState/LoadingState'
import PageHeader from '../components/common/PageHeader/PageHeader'
import StatCard from '../components/common/StatCard/StatCard'
import AddPositionDialog from '../features/portfolio/components/AddPositionDialog'
import PositionsTable from '../features/portfolio/components/PositionsTable'
import { usePortfolio } from '../features/portfolio/hooks/usePortfolio'

function formatCurrency(value: number): string {
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

/**
 * Portfolio page: GET /api/portfolio's equity summary + positions table, and
 * the entry point for adding a position. Stays thin per Frontend.md §3 — all
 * fetching lives in usePortfolio/useAddPosition/useDeletePosition, all
 * domain rendering lives in PositionsTable/AddPositionDialog.
 */
export default function PortfolioPage() {
  const portfolioQuery = usePortfolio()
  const [addDialogOpen, setAddDialogOpen] = useState(false)

  const existingTickers = useMemo(
    () => portfolioQuery.data?.positions.map((position) => position.ticker) ?? [],
    [portfolioQuery.data],
  )

  return (
    <>
      <PageHeader
        title="Portfolio"
        action={
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => setAddDialogOpen(true)}
          >
            Add Position
          </Button>
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
        </Stack>
      )}

      <AddPositionDialog
        open={addDialogOpen}
        onClose={() => setAddDialogOpen(false)}
        existingTickers={existingTickers}
      />
    </>
  )
}
