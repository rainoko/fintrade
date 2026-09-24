import Stack from '@mui/material/Stack'
import ErrorState from '../components/common/ErrorState/ErrorState'
import LoadingState from '../components/common/LoadingState/LoadingState'
import PageHeader from '../components/common/PageHeader/PageHeader'
import StatCard from '../components/common/StatCard/StatCard'
import PositionsGlanceTable from '../features/portfolio/components/PositionsGlanceTable'
import RiskSummaryCard from '../features/portfolio/components/RiskSummaryCard'
import SellFlaggedPositionsCard from '../features/portfolio/components/SellFlaggedPositionsCard'
import { usePortfolio } from '../features/portfolio/hooks/usePortfolio'
import TickerSearchBox from '../features/stocks/components/TickerSearchBox'
import { formatCurrency } from '../utils/format'

/**
 * The landing page ('/'): an at-a-glance summary composed entirely from
 * data/hooks the Portfolio page and its risk panel already wired
 * (usePortfolio, usePortfolioRisk via RiskSummaryCard/SellFlaggedPositionsCard)
 * plus a ticker lookup for jumping straight into stock analysis — no new API
 * calls, per this task's description. Stays thin per Frontend.md §3: all
 * fetching lives in usePortfolio/usePortfolioRisk, all domain rendering lives
 * in RiskSummaryCard/SellFlaggedPositionsCard/PositionsGlanceTable.
 */
export default function DashboardPage() {
  const portfolioQuery = usePortfolio()

  return (
    <>
      <PageHeader title="Dashboard" action={<TickerSearchBox />} />

      {portfolioQuery.isLoading && <LoadingState message="Loading dashboard..." />}
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

          <RiskSummaryCard />

          {/*
            RiskSummaryCard (above) already fully gates its own body -- and
            renders a common/ErrorState -- on the exact same usePortfolioRisk
            failure this card would otherwise also surface, so it's the
            explicit, caller-declared error owner here (see
            SellFlaggedPositionsCard's own errorSurfacedBySibling doc
            comment: this is an explicit opt-in, not an implicit "whichever
            sibling renders first" assumption -- if RiskSummaryCard is ever
            removed from this composition, this prop must be removed too).
          */}
          <SellFlaggedPositionsCard errorSurfacedBySibling />

          <PositionsGlanceTable positions={portfolioQuery.data.positions} />
        </Stack>
      )}
    </>
  )
}
