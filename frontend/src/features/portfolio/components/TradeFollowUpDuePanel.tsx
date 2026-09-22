import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useState } from 'react'
import type { ClosedTradeOut } from '../../../api/portfolio'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import SignedCurrency from '../../../components/common/SignedCurrency/SignedCurrency'
import TickerLink from '../../../components/common/TickerLink/TickerLink'
import { formatDate } from '../../../utils/format'
import { useDueForFollowUpTrades } from '../hooks/useClosedTrades'
import FollowUpReviewDialog from './FollowUpReviewDialog'

/**
 * Trades due right now for Elder's mandatory two-months-later follow-up
 * review (ch. 59 Trade Journal Section E, docs/ideas.md's ch. 59 entry) —
 * `GET /api/portfolio/closed-trades?due_for_follow_up=true`
 * (docs/architecture/API.md). This app has no scheduled job/notification, so
 * this panel is the only prompt a user gets that these trades are due; the
 * backend's own 8-10-week window (not a single exact date) means a trade
 * stays visible here across several visits rather than being missed the
 * moment one exact day passes (see the `backend-trade-journal-followup-review`
 * task's `decisions` entry).
 *
 * A section of the existing Portfolio page (alongside `TradeJournalPanel`,
 * not folded into it) — see this task's `decisions` entry for why a
 * dedicated panel was chosen over extending `TradeJournalPanel` itself.
 * Feature component: every field here (`ClosedTradeOut`, a ticker, a trade
 * id) is a portfolio domain concept, and it owns its own
 * `useDueForFollowUpTrades` call so `PortfolioPage` stays a thin composition
 * (Frontend.md §3), same pattern `TradeJournalPanel`/`RiskPanel` establish.
 */
export default function TradeFollowUpDuePanel() {
  const [reviewingTrade, setReviewingTrade] = useState<ClosedTradeOut | null>(null)
  const dueTradesQuery = useDueForFollowUpTrades()

  const columns: DataTableColumn<ClosedTradeOut>[] = [
    {
      key: 'ticker',
      header: 'Ticker',
      sortable: true,
      render: (row) => <TickerLink ticker={row.ticker} />,
    },
    {
      key: 'exit_date',
      header: 'Exited',
      sortable: true,
      render: (row) => formatDate(row.exit_date),
    },
    {
      key: 'realized_pnl',
      header: 'Realized P/L',
      sortable: true,
      align: 'right',
      render: (row) => <SignedCurrency value={row.realized_pnl} />,
    },
    {
      key: 'id',
      header: '',
      align: 'right',
      render: (row) => (
        <Button size="small" variant="outlined" onClick={() => setReviewingTrade(row)}>
          Record Review
        </Button>
      ),
    },
  ]

  // Checked in this order (data first) for the same reason TradeJournalPanel
  // does: this query has no `enabled: false`/pagination that could leave it
  // settled with neither data nor an error.
  if (!dueTradesQuery.data) {
    if (dueTradesQuery.isError) {
      return <ErrorState error={dueTradesQuery.error} />
    }
    return <LoadingState message="Loading trades due for follow-up review..." />
  }

  return (
    <Stack spacing={1}>
      <Typography variant="h6" component="h2">
        Due for Follow-Up Review
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Trades exited roughly two months ago, not yet reopened with the benefit of
        hindsight (Elder ch. 59 Trade Journal Section E).
      </Typography>

      <DataTable
        columns={columns}
        rows={dueTradesQuery.data.items}
        getRowKey={(row) => row.id}
        emptyMessage="No trades currently due for a follow-up review."
        ariaLabel="Trades due for follow-up review"
      />

      <FollowUpReviewDialog trade={reviewingTrade} onClose={() => setReviewingTrade(null)} />
    </Stack>
  )
}
