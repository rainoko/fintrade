import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlineOutlined'
import Box from '@mui/material/Box'
import IconButton from '@mui/material/IconButton'
import { useState } from 'react'
import type { PositionOut, RiskPosition } from '../../../api/portfolio'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import PercentChange from '../../../components/common/PercentChange/PercentChange'
import SignalBadge from '../../../components/common/SignalBadge/SignalBadge'
import TickerLink from '../../../components/common/TickerLink/TickerLink'
import { formatCurrency, formatNullableCurrency } from '../../../utils/format'
import { useDeletePosition } from '../hooks/useDeletePosition'
import { usePortfolioRisk } from '../hooks/usePortfolioRisk'
import ClosePositionDialog, { type ClosePositionConfirmValues } from './ClosePositionDialog'
import PositionProfitTargetCell from './PositionProfitTargetCell'

export interface PositionsTableProps {
  positions: PositionOut[]
}

/**
 * Positions table for the Portfolio page, built on common/DataTable. Owns
 * the close-position flow end to end (ClosePositionDialog + useDeletePosition
 * mutation) so PortfolioPage itself stays a thin composition (Frontend.md §3).
 * The Signal column reuses the exact common/SignalBadge + '—' null-fallback
 * pattern WatchlistTable established (frontend-lists-show-signal) rather than
 * a second implementation. A row's own Delete button is disabled while
 * `deletePosition` is pending *for that row's id specifically* (`variables
 * ?.id === row.id`, not just `isPending`) — same double-click-race guard
 * WatchlistTable's own Remove button uses (frontend-watchlist-page-followups).
 *
 * `useDeletePosition()` is instantiated here rather than inside
 * ClosePositionDialog itself (unlike AddPositionDialog/FollowUpReviewDialog/
 * TradeApgarDialog, each of which owns its own mutation) specifically so its
 * `isPending`/`variables` also drive the row-level double-click guard above,
 * outside the dialog — a second, independent `useDeletePosition()` call
 * inside the dialog wouldn't share that pending state with this table's own
 * row button. See ClosePositionDialog's own doc comment and this task's
 * `decisions` entry.
 *
 * Protective Stop and Profit Target columns (frontend-position-risk-columns)
 * read from GET /api/portfolio/risk via this component's own
 * usePortfolioRisk call, cross-referenced against each row by ticker the
 * same way RiskPanel's own Signal column cross-references `positions` by
 * ticker in the other direction -- PositionOut itself carries neither
 * field. This duplicates RiskPanel's usePortfolioRisk() call rather than
 * PortfolioPage fetching it once and passing risk data down to both: every
 * other data dependency here (useDeletePosition) is already
 * component-owned rather than prop-drilled, TanStack Query dedupes the
 * identical queryKey into a single network request regardless, and a
 * shared-prop version would mean changing RiskPanel's own established prop
 * contract too, for a table now doing exactly what RiskPanel already does
 * for its own columns. See this task's `decisions` entry.
 *
 * A genuine `riskQuery.isError` degrades silently to the same per-row '—'
 * fallback `riskByTicker` already renders for a ticker simply absent from a
 * *successful* risk response -- this component does NOT render its own
 * `ErrorState` for it. RiskPanel (driven by the exact same
 * usePortfolioRisk() hook/queryKey) already renders a full `ErrorState` for
 * this identical failure, and both components render together on
 * PortfolioPage -- a second, identical `ErrorState` here would stack two
 * duplicate `role="alert"` blocks on the same page for the one underlying
 * failure. See this task's `decisions` entry (corrected after PR #258's
 * review) for why an earlier revision of this task added, then removed,
 * that second block.
 */
export default function PositionsTable({ positions }: PositionsTableProps) {
  const [pendingDelete, setPendingDelete] = useState<PositionOut | null>(null)
  const deletePosition = useDeletePosition()
  const riskQuery = usePortfolioRisk()

  const riskByTicker = new Map<string, RiskPosition>(
    (riskQuery.data?.positions ?? []).map((riskPosition) => [
      riskPosition.ticker,
      riskPosition,
    ]),
  )

  const columns: DataTableColumn<PositionOut>[] = [
    {
      key: 'ticker',
      header: 'Ticker',
      sortable: true,
      render: (row) => <TickerLink ticker={row.ticker} />,
    },
    { key: 'quantity', header: 'Quantity', sortable: true, align: 'right' },
    {
      key: 'avg_cost_basis',
      header: 'Avg Cost Basis',
      sortable: true,
      align: 'right',
      render: (row) => formatCurrency(row.avg_cost_basis),
    },
    { key: 'entry_date', header: 'Entry Date', sortable: true },
    {
      // Sortable: current_price/unrealized_pnl_pct can be null (a failed
      // price fetch, API.md), but DataTable's own compareForSort already
      // defines null-sorts-last ordering for exactly that case regardless
      // of the column's custom `render` (frontend-trade-journal-followups).
      key: 'current_price',
      header: 'Current Price',
      sortable: true,
      align: 'right',
      render: (row) => formatNullableCurrency(row.current_price),
    },
    {
      key: 'unrealized_pnl_pct',
      header: 'Unrealized P/L',
      sortable: true,
      align: 'right',
      render: (row) =>
        row.unrealized_pnl_pct === null || row.unrealized_pnl_pct === undefined ? (
          '—'
        ) : (
          <PercentChange value={row.unrealized_pnl_pct} />
        ),
    },
    {
      // Synthetic column: `RiskPosition.protective_stop` isn't a field of
      // `PositionOut`, so `key` can't be `'protective_stop'` --
      // `DataTableColumn<T>.key` is typed `keyof T` and is only ever used
      // as this column's own React key/non-sortable header, not a lookup
      // into the row -- reuses one of `PositionOut`'s own otherwise-
      // column-unused fields purely for that typing, same convention
      // RiskPanel's own synthetic Signal/Profit Target columns use.
      key: 'confidence',
      header: 'Protective Stop',
      align: 'right',
      render: (row) => {
        const risk = riskByTicker.get(row.ticker)
        return risk ? formatCurrency(risk.protective_stop) : '—'
      },
    },
    {
      // Synthetic column, same convention as Protective Stop above.
      key: 'confidence_band',
      header: 'Profit Target',
      align: 'right',
      render: (row) => (
        <PositionProfitTargetCell
          profitTarget={riskByTicker.get(row.ticker)?.profit_target ?? null}
        />
      ),
    },
    {
      key: 'signal',
      header: 'Signal',
      // `signal` is optional-and-nullable in PositionOut, matching
      // WatchlistItemOut's own null-on-failure case (API.md) — same '—'
      // fallback, loose `== null` narrowing both `undefined` and `null` in
      // one check.
      render: (row) => (row.signal == null ? '—' : <SignalBadge signal={row.signal} />),
    },
    {
      key: 'id',
      header: '',
      align: 'right',
      render: (row) => (
        <IconButton
          aria-label={`Delete ${row.ticker}`}
          size="small"
          disabled={deletePosition.isPending && deletePosition.variables?.id === row.id}
          onClick={() => setPendingDelete(row)}
        >
          <DeleteOutlineIcon fontSize="small" />
        </IconButton>
      ),
    },
  ]

  const handleConfirmClose = (values: ClosePositionConfirmValues) => {
    // ClosePositionDialog's onConfirm only fires while it's open, and it's
    // only open while pendingDelete !== null (see the `position` prop
    // below), so this guard is unreachable through the UI in practice — it
    // exists purely so TypeScript narrows `pendingDelete` from
    // `PositionOut | null` before `.id` is read below. Intentionally-
    // defensive dead code, not a bug; /* v8 ignore next 3 */ keeps it out of
    // the branch-coverage denominator instead of it showing up as a real gap
    // on future coverage sweeps.
    /* v8 ignore next 3 */
    if (!pendingDelete) {
      return
    }
    deletePosition.mutate(
      { id: pendingDelete.id, ...values },
      // The dialog only closes on success -- an error leaves it open with
      // its own ErrorState visible (see ClosePositionDialog), so the user
      // can retry or cancel instead of the error appearing after the dialog
      // has already vanished.
      { onSuccess: () => setPendingDelete(null) },
    )
  }

  const handleCancelClose = () => {
    setPendingDelete(null)
    // Clears any error from a previous failed close attempt so reopening
    // this dialog for a different position doesn't start by showing a stale
    // ErrorState for an unrelated earlier failure -- but only when nothing is
    // actually still in flight. ClosePositionDialog's own Cancel button is
    // already disabled while pending, but a backdrop click still fires this
    // same handler regardless of pending state; calling `reset()` in that
    // case would flip `isPending` back to false immediately even though the
    // DELETE request itself is still running in the background, defeating
    // the row icon's own double-click-race guard above (a second click could
    // reopen this dialog and fire a second DELETE for the same position
    // before the first one already in flight has resolved).
    if (!deletePosition.isPending) {
      deletePosition.reset()
    }
  }

  return (
    <Box>
      <DataTable
        columns={columns}
        rows={positions}
        getRowKey={(row) => row.id}
        emptyMessage="No positions yet. Add one to get started."
        ariaLabel="Positions"
      />
      <ClosePositionDialog
        position={pendingDelete}
        isPending={deletePosition.isPending}
        error={deletePosition.error}
        onConfirm={handleConfirmClose}
        onCancel={handleCancelClose}
      />
    </Box>
  )
}
