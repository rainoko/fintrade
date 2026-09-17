import Stack from '@mui/material/Stack'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import RiskBreachBanner from '../../../components/common/RiskBreachBanner/RiskBreachBanner'
import StatCard from '../../../components/common/StatCard/StatCard'
import { usePortfolioRisk } from '../hooks/usePortfolioRisk'

/**
 * Dashboard-level condensed view of `GET /api/portfolio/risk`
 * (docs/architecture/API.md#get-apiportfoliorisk, docs/Analyse.md §7): the
 * total open risk, a count of positions currently breaching the 2% rule, and
 * the same prominent 6%-rule breach banner as the full RiskPanel (Portfolio
 * page) — condensed to two stats rather than the full per-position table,
 * which stays on the Portfolio page. Feature component (not `common/`),
 * same reasoning as RiskPanel: every field it renders is a portfolio-risk
 * domain concept, and it owns its own usePortfolioRisk call so DashboardPage
 * stays a thin composition (Frontend.md §3).
 */
export default function RiskSummaryCard() {
  const riskQuery = usePortfolioRisk()

  if (!riskQuery.data) {
    if (riskQuery.isError) {
      return <ErrorState error={riskQuery.error} />
    }
    return <LoadingState message="Loading risk summary..." />
  }

  const { total_open_risk_pct, six_percent_rule_breached, positions } = riskQuery.data
  const breachedCount = positions.filter(
    (position) => position.two_percent_rule_breached,
  ).length

  return (
    <Stack spacing={2}>
      {six_percent_rule_breached && (
        <RiskBreachBanner
          message={
            <>
              6% rule breached — total open risk is {total_open_risk_pct.toFixed(2)}% of
              equity (limit 6%). See the Portfolio page for details.
            </>
          }
        />
      )}

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
        <StatCard label="Total Open Risk" value={`${total_open_risk_pct.toFixed(2)}%`} />
        <StatCard label="Positions Breaching 2% Rule" value={String(breachedCount)} />
      </Stack>
    </Stack>
  )
}
