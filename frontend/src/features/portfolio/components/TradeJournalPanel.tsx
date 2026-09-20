import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'
import type { ClosedTradeOut } from '../../../api/portfolio'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import SignedCurrency from '../../../components/common/SignedCurrency/SignedCurrency'
import TickerLink from '../../../components/common/TickerLink/TickerLink'
import { formatCurrency, formatDate, humanizeSnakeCase } from '../../../utils/format'
import { EXIT_REASON_LABELS } from '../exitReasonLabels'
import { useClosedTrades } from '../hooks/useClosedTrades'
import { buyGradeHelp, sellGradeHelp, tradeGradeHelp } from './metricHelpContent'

// Elder's own documented "very good"/"A trade" anchors (docs/Analyse.md §7)
// -- the only grade thresholds this panel colors by. Buy/Sell Grade share
// one anchor (>50%); Trade Grade's is different (~30%+ for an "A"). Neither
// full A-F letter-grade boundary is documented, so this panel deliberately
// shows the raw percentage (via the grade's own MetricHelp) rather than
// inventing an unstated B/D/F cutoff -- see this task's `decisions` entry.
const BUY_SELL_GOOD_THRESHOLD_PCT = 50
const TRADE_GOOD_THRESHOLD_PCT = 30

type GradeHelp = {
  metricLabel: string
  definition: string
  elderContext: string
  interpretValue: (gradePct: number | null) => string
}

/** One grade cell: the percentage (or an em dash when unavailable) plus a `MetricHelp` explaining the formula and, when known, this specific value in plain terms -- per this task's checklist item. */
function GradeCell({
  gradePct,
  help,
  goodThresholdPct,
  strictlyAbove = false,
}: {
  gradePct: number | null
  help: GradeHelp
  goodThresholdPct: number
  /**
   * Whether the "good" cutoff is a strict `>` rather than `>=`. Buy/Sell
   * Grade's own MetricHelp copy and backend/app/api/schemas.py's docstring
   * both describe their 50% anchor as strictly "over 50%" -- so a value of
   * exactly 50.0% should render as the "not yet good" weight, not bold
   * (frontend-trade-journal-followups). Trade Grade's "~30%+" copy is
   * inclusive by its own wording, so it keeps the default `>=`.
   */
  strictlyAbove?: boolean
}) {
  const theme = useTheme()
  const isGood =
    gradePct !== null && (strictlyAbove ? gradePct > goodThresholdPct : gradePct >= goodThresholdPct)
  const color = gradePct === null ? theme.palette.text.secondary : undefined

  return (
    <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
      <Typography
        component="span"
        style={{ color, fontWeight: isGood ? 700 : 400 }}
      >
        {gradePct === null ? '—' : `${gradePct.toFixed(1)}%`}
      </Typography>
      <MetricHelp
        metricLabel={help.metricLabel}
        definition={help.definition}
        elderContext={help.elderContext}
        valueInterpretation={help.interpretValue(gradePct)}
      />
    </Stack>
  )
}

const columns: DataTableColumn<ClosedTradeOut>[] = [
  {
    key: 'ticker',
    header: 'Ticker',
    sortable: true,
    render: (row) => <TickerLink ticker={row.ticker} />,
  },
  { key: 'quantity', header: 'Quantity', sortable: true, align: 'right' },
  {
    key: 'entry_date',
    header: 'Entry',
    sortable: true,
    render: (row) => `${formatDate(row.entry_date)} @ ${formatCurrency(row.entry_price)}`,
  },
  {
    key: 'exit_date',
    header: 'Exit',
    sortable: true,
    render: (row) => `${formatDate(row.exit_date)} @ ${formatCurrency(row.exit_price)}`,
  },
  {
    key: 'realized_pnl',
    header: 'Realized P/L',
    sortable: true,
    align: 'right',
    render: (row) => <SignedCurrency value={row.realized_pnl} />,
  },
  {
    key: 'exit_reason',
    header: 'Exit Reason',
    render: (row) => (
      <Chip
        label={humanizeSnakeCase(row.exit_reason, EXIT_REASON_LABELS)}
        size="small"
      />
    ),
  },
  {
    // Sortable: the underlying value is a plain nullable number, and
    // DataTable's own compareForSort already defines null-sorts-last
    // ordering for exactly that case regardless of the column's custom
    // `render` (frontend-trade-journal-followups; the same fix applies to
    // PositionsTable.tsx's current_price column).
    key: 'buy_grade_pct',
    header: 'Buy Grade',
    sortable: true,
    render: (row) => (
      <GradeCell
        gradePct={row.buy_grade_pct ?? null}
        help={buyGradeHelp}
        goodThresholdPct={BUY_SELL_GOOD_THRESHOLD_PCT}
        strictlyAbove
      />
    ),
  },
  {
    key: 'sell_grade_pct',
    header: 'Sell Grade',
    sortable: true,
    render: (row) => (
      <GradeCell
        gradePct={row.sell_grade_pct ?? null}
        help={sellGradeHelp}
        goodThresholdPct={BUY_SELL_GOOD_THRESHOLD_PCT}
        strictlyAbove
      />
    ),
  },
  {
    key: 'trade_grade_pct',
    header: 'Trade Grade',
    sortable: true,
    render: (row) => (
      <GradeCell
        gradePct={row.trade_grade_pct ?? null}
        help={tradeGradeHelp}
        goodThresholdPct={TRADE_GOOD_THRESHOLD_PCT}
      />
    ),
  },
]

/**
 * Trade journal: closed-trade history from `GET /api/portfolio/closed-trades`
 * (docs/architecture/API.md, docs/Analyse.md §7's trade-history/ledger
 * table), each row annotated with its buy/sell/trade "A-trade" grades
 * (Elder ch. 55 "Is This an A-Trade?") and its exit-reason tag. A section of
 * the existing Portfolio page (not a standalone route) -- see this task's
 * `decisions` entry for the placement rationale, and the feature
 * component's own `useClosedTrades` call so PortfolioPage stays a thin
 * composition (Frontend.md §3), same pattern RiskPanel/
 * SellFlaggedPositionsCard already establish.
 *
 * Grading a completed trade by how much of what was *realistically
 * available* got captured (channel-height-based Trade Grade), not raw P&L
 * alone, is Elder's own emphasis -- a profitable trade can still be a "C",
 * and a barely-profitable one can be an "A" (docs/Analyse.md §7). Each grade
 * cell carries its own `MetricHelp` explaining the formula and this
 * specific value in plain terms (e.g. "you sold at 35.5% up the day's
 * range"), not just the bare percentage, per this task's checklist.
 */
export default function TradeJournalPanel() {
  const closedTradesQuery = useClosedTrades()

  // Checked in this order (data first) for the same reason RiskPanel does:
  // this query has no `enabled: false`/pagination that could leave it
  // settled with neither data nor an error.
  if (!closedTradesQuery.data) {
    if (closedTradesQuery.isError) {
      return <ErrorState error={closedTradesQuery.error} />
    }
    return <LoadingState message="Loading trade journal..." />
  }

  return (
    <Stack spacing={1}>
      <Typography variant="h6" component="h2">
        Trade Journal
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Every closed trade, most recently exited first. Reviewing exit reasons over time is
        exactly the kind of segmented review Elder credits with improving his own trading
        (docs/Analyse.md §7).
      </Typography>

      <DataTable
        columns={columns}
        rows={closedTradesQuery.data.items}
        getRowKey={(row) => row.id}
        emptyMessage="No closed trades yet."
        ariaLabel="Trade journal"
      />
    </Stack>
  )
}
