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
import { formatCurrency } from '../../../utils/format'
import { useDeletePosition } from '../hooks/useDeletePosition'

export interface PositionsTableProps {
  positions: PositionOut[]
}

// current_price/unrealized_pnl_pct are null only when the latest price fetch
// for that ticker failed (API.md) — rendered as an em dash so it reads as
// "unknown", not "zero", per this task's checklist item on handling nulls.
function formatNullableCurrency(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : formatCurrency(value)
}

/**
 * Positions table for the Portfolio page, built on common/DataTable. Owns
 * the delete-position flow end to end (confirm dialog + useDeletePosition
 * mutation) so PortfolioPage itself stays a thin composition (Frontend.md §3).
 */
export default function PositionsTable({ positions }: PositionsTableProps) {
  const [pendingDelete, setPendingDelete] = useState<PositionOut | null>(null)
  const deletePosition = useDeletePosition()

  const columns: DataTableColumn<PositionOut>[] = [
    { key: 'ticker', header: 'Ticker', sortable: true },
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
      // Not sortable: current_price/unrealized_pnl_pct can be null (a
      // failed price fetch, API.md), and DataTable's generic comparator has
      // no defined ordering for null vs. numeric values.
      key: 'current_price',
      header: 'Current Price',
      align: 'right',
      render: (row) => formatNullableCurrency(row.current_price),
    },
    {
      key: 'unrealized_pnl_pct',
      header: 'Unrealized P/L',
      align: 'right',
      render: (row) =>
        row.unrealized_pnl_pct === null || row.unrealized_pnl_pct === undefined ? (
          '—'
        ) : (
          <PercentChange value={row.unrealized_pnl_pct} />
        ),
    },
    {
      key: 'id',
      header: '',
      align: 'right',
      render: (row) => (
        <IconButton
          aria-label={`Delete ${row.ticker}`}
          size="small"
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
