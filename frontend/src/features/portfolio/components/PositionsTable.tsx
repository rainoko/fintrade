import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlineOutlined'
import Box from '@mui/material/Box'
import IconButton from '@mui/material/IconButton'
import { useState } from 'react'
import type { PositionOut } from '../../../api/portfolio'
import ConfirmDialog from '../../../components/common/ConfirmDialog/ConfirmDialog'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import PercentChange from '../../../components/common/PercentChange/PercentChange'
import SignalBadge from '../../../components/common/SignalBadge/SignalBadge'
import TickerLink from '../../../components/common/TickerLink/TickerLink'
import { formatCurrency, formatNullableCurrency } from '../../../utils/format'
import { useDeletePosition } from '../hooks/useDeletePosition'

export interface PositionsTableProps {
  positions: PositionOut[]
}

/**
 * Positions table for the Portfolio page, built on common/DataTable. Owns
 * the delete-position flow end to end (confirm dialog + useDeletePosition
 * mutation) so PortfolioPage itself stays a thin composition (Frontend.md §3).
 * The Signal column reuses the exact common/SignalBadge + '—' null-fallback
 * pattern WatchlistTable established (frontend-lists-show-signal) rather than
 * a second implementation. A row's own Delete button is disabled while
 * `deletePosition` is pending *for that row's id specifically* (`variables
 * === row.id`, not just `isPending`) — same double-click-race guard
 * WatchlistTable's own Remove button uses (frontend-watchlist-page-followups).
 */
export default function PositionsTable({ positions }: PositionsTableProps) {
  const [pendingDelete, setPendingDelete] = useState<PositionOut | null>(null)
  const deletePosition = useDeletePosition()

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
          disabled={deletePosition.isPending && deletePosition.variables === row.id}
          onClick={() => setPendingDelete(row)}
        >
          <DeleteOutlineIcon fontSize="small" />
        </IconButton>
      ),
    },
  ]

  const handleConfirmDelete = () => {
    // ConfirmDialog's onConfirm only fires while it's open, and it's only
    // open while pendingDelete !== null (see the `open` prop below), so this
    // guard is unreachable through the UI in practice — it exists purely so
    // TypeScript narrows `pendingDelete` from `PositionOut | null` before
    // `.id` is read below. Intentionally-defensive dead code, not a bug;
    // /* v8 ignore next 3 */ keeps it out of the branch-coverage denominator
    // instead of it showing up as a real gap on future coverage sweeps.
    /* v8 ignore next 3 */
    if (!pendingDelete) {
      return
    }
    deletePosition.mutate(pendingDelete.id)
    setPendingDelete(null)
  }

  return (
    <Box>
      {deletePosition.isError && (
        <Box sx={{ mb: 2 }}>
          <ErrorState error={deletePosition.error} />
        </Box>
      )}
      <DataTable
        columns={columns}
        rows={positions}
        getRowKey={(row) => row.id}
        emptyMessage="No positions yet. Add one to get started."
        ariaLabel="Positions"
      />
      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete position"
        body={
          pendingDelete
            ? `Delete ${pendingDelete.ticker} (${pendingDelete.quantity} shares)? This cannot be undone.`
            : ''
        }
        confirmLabel="Delete"
        destructive
        onConfirm={handleConfirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </Box>
  )
}
