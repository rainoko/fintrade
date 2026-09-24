import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import type { RiskPosition } from '../../../api/portfolio'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import TickerLink from '../../../components/common/TickerLink/TickerLink'
import ExitFlagChips from './ExitFlagChips'
import { usePortfolioRisk } from '../hooks/usePortfolioRisk'

export interface SellFlaggedPositionsCardProps {
  /**
   * Set by a caller that already renders another component surfacing the
   * exact same `GET /api/portfolio/risk` failure (today: `DashboardPage`
   * passes `true` because `RiskSummaryCard`, mounted alongside this card,
   * already fully gates its own body — and shows a `common/ErrorState` —
   * on `usePortfolioRisk`'s `isError`; both components share the identical
   * hook/query key, so rendering a second `ErrorState` here would just
   * duplicate the first one). Defaults to `false`, so a standalone mount of
   * this card (no such sibling) still surfaces a real fetch failure instead
   * of silently rendering nothing.
   *
   * This is an explicit, caller-supplied contract rather than an implicit
   * "whichever sibling happens to render first/already handles it" rule —
   * see this task's `decisions` entry (frontend-position-risk-columns-
   * followups-followups-followups) for why: the previous implementation
   * always returned `null` on `isError` unconditionally, which relied on
   * `RiskSummaryCard` always being mounted as a sibling that fully gates on
   * this same failure. Nothing enforced that pairing — a future page that
   * mounted this card alone, or before its error-owning sibling, would have
   * shown nothing at all on a genuine failure, with no visible error and no
   * console warning. Requiring the caller to say so explicitly makes the
   * dependency visible at the composition site and keeps the safe default
   * (show the error) for any caller that doesn't opt out of it.
   */
  errorSurfacedBySibling?: boolean
}

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
 * On `riskQuery.isError`, renders its own `common/ErrorState` UNLESS the
 * caller passes `errorSurfacedBySibling` (see that prop's own doc comment
 * for the sibling-duplication history this guards against and why it's an
 * explicit opt-in rather than an implicit render-order assumption).
 * `DashboardPage` passes `true` since `RiskSummaryCard` (its sibling here)
 * already fully gates its own body on this exact `GET /api/portfolio/risk`
 * failure — the same sibling-duplication shape `pr-reviewer` found blocking
 * on PortfolioPage's PositionsTable/RiskPanel (PR #258). This card has no
 * unaffected content of its own to fall back to when suppressing (unlike
 * PositionsTable's other, risk-independent columns), so suppressing means
 * rendering nothing at all rather than a degraded placeholder.
 */
export default function SellFlaggedPositionsCard({
  errorSurfacedBySibling = false,
}: SellFlaggedPositionsCardProps) {
  const riskQuery = usePortfolioRisk()

  if (riskQuery.isError) {
    return errorSurfacedBySibling ? null : <ErrorState error={riskQuery.error} />
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
