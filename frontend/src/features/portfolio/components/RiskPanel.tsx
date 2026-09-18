import Box from '@mui/material/Box'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'
import type { PositionOut, RiskPosition } from '../../../api/portfolio'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import RiskBreachBanner from '../../../components/common/RiskBreachBanner/RiskBreachBanner'
import RiskPercent from '../../../components/common/RiskPercent/RiskPercent'
import StatCard from '../../../components/common/StatCard/StatCard'
import TickerLink from '../../../components/common/TickerLink/TickerLink'
import { formatCurrency } from '../../../utils/format'
import ExitFlagChips from './ExitFlagChips'
import { usePortfolioRisk } from '../hooks/usePortfolioRisk'

export interface RiskPanelProps {
  /**
   * The full held-position list (from usePortfolio/GET /api/portfolio), used
   * only to cross-reference against `risk.positions` so a position silently
   * excluded from the risk response (API.md's documented degrade-gracefully
   * rule) still gets a non-blocking, informational acknowledgment instead of
   * no acknowledgment at all — see this task's `decisions` entry.
   */
  positions: PositionOut[]
}

/**
 * Portfolio-level 2%/6% rule panel for `GET /api/portfolio/risk`
 * (docs/architecture/API.md#get-apiportfoliorisk, docs/Analyse.md §7).
 * Feature component (not `common/`) since every field it renders — protective
 * stop, position risk, exit flags — is a portfolio-risk domain concept.
 */
export default function RiskPanel({ positions }: RiskPanelProps) {
  const theme = useTheme()
  const riskQuery = usePortfolioRisk()

  // Checked in this order (data first) rather than isLoading/isError first
  // followed by a defensive `if (!riskQuery.data) return null`: this query
  // has no `enabled: false`/pagination that could leave it settled with
  // neither data nor an error, so that guard would be permanently
  // unreachable dead code — see this task's `decisions` entry.
  if (!riskQuery.data) {
    if (riskQuery.isError) {
      return <ErrorState error={riskQuery.error} />
    }
    return <LoadingState message="Loading risk data..." />
  }

  const {
    total_open_risk_pct,
    six_percent_rule_breached,
    positions: riskPositions,
  } = riskQuery.data

  // API.md: a position whose risk can't be computed at all (price fetch
  // failed, too little history, ...) is silently absent from `positions`
  // rather than appearing with null/partial fields. Cross-referencing the
  // full held-position list against `riskPositions` surfaces that gap as a
  // non-blocking informational note instead of leaving it unacknowledged —
  // see this task's `decisions` entry for the rejected alternatives.
  const riskTickers = new Set(riskPositions.map((riskPosition) => riskPosition.ticker))
  const missingTickers = positions
    .map((position) => position.ticker)
    .filter((ticker) => !riskTickers.has(ticker))
  // Plural pronoun agreement for the note below: "its"/"it's" reads wrong
  // once more than one ticker is joined into the list (e.g. "ZZZZINVALID,
  // TSLA — its price..."). See this task's `decisions` entry.
  const isMissingPlural = missingTickers.length > 1

  const columns: DataTableColumn<RiskPosition>[] = [
    {
      key: 'ticker',
      header: 'Ticker',
      sortable: true,
      render: (row) => <TickerLink ticker={row.ticker} />,
    },
    {
      key: 'protective_stop',
      header: 'Protective Stop',
      align: 'right',
      sortable: true,
      render: (row) => formatCurrency(row.protective_stop),
    },
    {
      key: 'position_risk_pct',
      header: 'Position Risk',
      align: 'right',
      sortable: true,
      render: (row) => (
        <RiskPercent
          value={row.position_risk_pct}
          breached={row.two_percent_rule_breached}
        />
      ),
    },
    {
      key: 'exit_flags',
      header: 'Exit Flags',
      render: (row) => <ExitFlagChips flags={row.exit_flags} />,
    },
  ]

  return (
    <Stack spacing={2}>
      {six_percent_rule_breached && (
        <RiskBreachBanner
          message={
            <>
              6% rule breached — total open risk is {total_open_risk_pct.toFixed(2)}% of
              equity (limit 6%). Consider trimming or closing your highest-risk
              position(s) first.
            </>
          }
        />
      )}

      <StatCard label="Total Open Risk" value={`${total_open_risk_pct.toFixed(2)}%`} />

      {missingTickers.length > 0 && (
        <Box
          role="status"
          sx={{
            p: 2,
            borderRadius: 1,
            border: '1px solid',
            borderColor: 'divider',
            backgroundColor: 'action.hover',
          }}
        >
          <Typography variant="body2" color="text.secondary">
            No risk data available for {missingTickers.join(', ')} —{' '}
            {isMissingPlural ? 'their price' : 'its price'} or history couldn't be
            fetched, so {isMissingPlural ? "they're" : "it's"} excluded from the risk
            table and total below.
          </Typography>
        </Box>
      )}

      <DataTable
        columns={columns}
        rows={riskPositions}
        getRowKey={(row) => row.id}
        getRowStyle={(row) =>
          row.two_percent_rule_breached
            ? { backgroundColor: theme.palette.riskBreach.background }
            : undefined
        }
        emptyMessage="No risk data available."
        ariaLabel="Portfolio risk"
      />
    </Stack>
  )
}
