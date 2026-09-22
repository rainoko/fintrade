import StickyNote2OutlinedIcon from '@mui/icons-material/StickyNote2Outlined'
import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'
import type { ClosedTradeOut } from '../../../api/portfolio'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import InfoBalloon from '../../../components/common/InfoBalloon/InfoBalloon'
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
// one anchor (>50%); Trade Grade's is different (~30%+ for an "A"). Only
// trade_grade_pct also carries an Elder-style A/B/C/D letter grade
// (backend-trade-grade-letter's `trade_letter_grade`, rendered by GradeCell
// below) -- buy_grade_pct/sell_grade_pct have no letter-grade scale
// documented in the book at all (only the single ">50%" anchor each), so
// they deliberately stay percentage-only.
const BUY_SELL_GOOD_THRESHOLD_PCT = 50
const TRADE_GOOD_THRESHOLD_PCT = 30

type GradeHelp = {
  metricLabel: string
  definition: string
  elderContext: string
  interpretValue: (gradePct: number | null) => string
}

/**
 * One grade cell: the percentage (or an em dash when unavailable), plus --
 * for `trade_grade_pct` only, via `letterGrade` -- Elder's own A/B/C/D
 * letter grade in parentheses (backend-trade-grade-letter), plus a
 * `MetricHelp` explaining the formula and, when known, this specific value
 * in plain terms -- per this task's checklist item.
 */
function GradeCell({
  gradePct,
  help,
  goodThresholdPct,
  strictlyAbove = false,
  letterGrade = null,
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
  /**
   * Elder's A/B/C/D letter grade for this value (`ClosedTradeOut.trade_letter_grade`),
   * shown in parentheses right after the percentage -- `null` for a column
   * with no letter-grade scale at all (buy/sell grade) as well as for a
   * trade_grade_pct that itself couldn't be computed (frontend-trade-grade-letter-display).
   */
  letterGrade?: 'A' | 'B' | 'C' | 'D' | null
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
        {gradePct === null
          ? '—'
          : `${gradePct.toFixed(1)}%${letterGrade === null ? '' : ` (${letterGrade})`}`}
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

/**
 * One "Notes" cell: an em dash when the trade has no `entry_notes` (the
 * common case, since the field is optional), or a small icon that opens an
 * `InfoBalloon` with the full note text when it does -- an expandable
 * detail rather than a dedicated full-width column, since most trades won't
 * have one and the note itself can be long free text (this task's
 * checklist; see this task's `decisions` entry for why `InfoBalloon` was
 * reused here rather than a new common component).
 */
function NotesCell({ entryNotes }: { entryNotes: string | null | undefined }) {
  if (!entryNotes) {
    return <Typography component="span">—</Typography>
  }

  return (
    <InfoBalloon
      triggerAriaLabel="View entry notes"
      title="Entry Notes"
      content={
        <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
          {entryNotes}
        </Typography>
      }
    >
      <StickyNote2OutlinedIcon fontSize="small" color="action" />
    </InfoBalloon>
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
        letterGrade={row.trade_letter_grade ?? null}
      />
    ),
  },
  {
    key: 'entry_notes',
    header: 'Notes',
    render: (row) => <NotesCell entryNotes={row.entry_notes} />,
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
 *
 * The Notes column surfaces `entry_notes` (Elder ch. 59 Trade Journal
 * Section A, "why did I take this trade") when the position had one --
 * an expandable detail via `NotesCell`/`InfoBalloon` rather than a raw
 * text column, since most trades won't have a note and the ones that do
 * can be long free text (frontend-trade-journal-entry-notes).
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
