import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import type { RiskPosition } from '../../../api/portfolio'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import TickerLink from '../../../components/common/TickerLink/TickerLink'
import ExitFlagChips from './ExitFlagChips'
import { usePortfolioRisk } from '../hooks/usePortfolioRisk'

const columns: DataTableColumn<RiskPosition>[] = [
  {
    key: 'ticker',
    header: 'Ticker',
    sortable: true,
    render: (row) => <TickerLink ticker={row.ticker} />,
  },
  {
    key: 'exit_flags',
    header: 'Exit Flags',
    render: (row) => <ExitFlagChips flags={row.exit_flags} />,
  },
]

/**
 * Dashboard-level list of every held position currently carrying a
 * risk-driven exit flag from `GET /api/portfolio/risk`
 * (docs/architecture/API.md#get-apiportfoliorisk, docs/Analyse.md §7
 * "Existing-position exit signals") — e.g. a stop hit, the 2%/6% rule, or the
 * Tide flipping bearish. Complements RiskSummaryCard's aggregate count with
 * the actual per-ticker breakdown, so a user can see *which* positions need
 * attention without visiting the full Portfolio page.
 *
 * Scoped to risk-driven `exit_flags` only, not a fresh technical SELL signal
 * from `GET /api/stocks/{ticker}/analysis` — see this task's `decisions`
 * entry for why that extension is out of scope here.
 *
 * Feature component (not `common/`): every field it renders (a position, a
 * ticker, an exit flag) is a portfolio-risk domain concept, and it owns its
 * own `usePortfolioRisk` call so DashboardPage stays a thin composition
 * (Frontend.md §3) — same reasoning as RiskSummaryCard/RiskPanel.
 *
 * Renders nothing (not its own `common/ErrorState`) on `riskQuery.isError`:
 * this card and `RiskSummaryCard` share the exact same `usePortfolioRisk`
 * hook/query key and are always rendered together as siblings on
 * DashboardPage, so a single underlying `GET /api/portfolio/risk` failure
 * previously produced two identical stacked `ErrorState` alerts — the same
 * sibling-duplication shape `pr-reviewer` found blocking on PortfolioPage's
 * PositionsTable/RiskPanel (PR #258). `RiskSummaryCard` renders first and
 * already fully gates its body on this exact failure, so it remains the
 * page's sole error surface for it; this card has no unaffected content of
 * its own to fall back to (unlike PositionsTable's other, risk-independent
 * columns), so returning `null` rather than a second alert (or a degraded
 * placeholder) is the more surgical fix. See this task's `decisions` entry.
 */
export default function SellFlaggedPositionsCard() {
  const riskQuery = usePortfolioRisk()

  if (riskQuery.isError) {
    return null
  }

  if (!riskQuery.data) {
    return <LoadingState message="Loading sell-flagged positions..." />
  }

  const flaggedPositions = riskQuery.data.positions.filter(
    (position) => position.exit_flags.length > 0,
  )

  return (
    <Stack spacing={1}>
      <Typography variant="h6" component="h2">
        Positions Flagged to Sell
      </Typography>

      <DataTable
        columns={columns}
        rows={flaggedPositions}
        getRowKey={(row) => row.id}
        emptyMessage="No positions currently flagged to sell."
        ariaLabel="Positions flagged to sell"
      />
    </Stack>
  )
}
