import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlineOutlined'
import Box from '@mui/material/Box'
import IconButton from '@mui/material/IconButton'
import { useState } from 'react'
import type { WatchlistItemOut } from '../../../api/watchlist'
import ConfidenceGauge from '../../../components/common/ConfidenceGauge/ConfidenceGauge'
import ConfirmDialog from '../../../components/common/ConfirmDialog/ConfirmDialog'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import SignalBadge from '../../../components/common/SignalBadge/SignalBadge'
import TickerLink from '../../../components/common/TickerLink/TickerLink'
import { formatDate } from '../../../utils/format'
import { useRemoveWatchlistItem } from '../hooks/useRemoveWatchlistItem'

export interface WatchlistTableProps {
  items: WatchlistItemOut[]
}

/**
 * Watchlist table: each watched ticker plus its current signal, using the
 * exact same `common/SignalBadge` colored-chip convention the stock analysis
 * page's SignalSummary uses to visually distinguish BUY from HOLD/SELL —
 * reused as-is rather than a second badge/color implementation (task
 * description). Confidence reuses `common/ConfidenceGauge` the same way,
 * passed the API's own `confidence_band` directly (not re-derived
 * client-side) for the same anti-drift reason SignalSummary does. A ticker
 * whose signal couldn't be computed (API.md's nullable-on-failure case) shows
 * '—' in both cells rather than a broken badge — SignalBadge/ConfidenceGauge
 * both require a non-null value, so null is handled here rather than pushed
 * into either component. Ticker cell uses the shared common/TickerLink
 * component (frontend-ticker-link), same as every other ticker-displaying
 * table. Owns the remove-ticker flow end to end (confirm dialog +
 * useRemoveWatchlistItem mutation) so WatchlistPage itself stays a thin
 * composition (Frontend.md §3).
 */
export default function WatchlistTable({ items }: WatchlistTableProps) {
  const [pendingRemove, setPendingRemove] = useState<WatchlistItemOut | null>(null)
  const removeWatchlistItem = useRemoveWatchlistItem()

  const columns: DataTableColumn<WatchlistItemOut>[] = [
    {
      key: 'ticker',
      header: 'Ticker',
      sortable: true,
      render: (row) => <TickerLink ticker={row.ticker} />,
    },
    {
      key: 'added_at',
      header: 'Added',
      sortable: true,
      render: (row) => formatDate(row.added_at),
    },
    {
      key: 'signal',
      header: 'Signal',
      // `signal` is optional-and-nullable in the generated type
      // (WatchlistItemOut, matching the backend's Pydantic `Optional`
      // field) — `== null` (loose) narrows out both `undefined` and `null`
      // in one check, since neither case is ever meaningfully distinct here
      // (API.md documents them as the same "signal couldn't be computed"
      // outcome, always alongside a null confidence/confidence_band too).
      render: (row) => (row.signal == null ? '—' : <SignalBadge signal={row.signal} />),
    },
    {
      key: 'confidence',
      header: 'Confidence',
      render: (row) =>
        row.confidence == null ? (
          '—'
        ) : (
          <ConfidenceGauge
            confidence={row.confidence}
            band={row.confidence_band ?? undefined}
          />
        ),
    },
    {
      // 'confidence_band' is the only WatchlistItemOut field not otherwise
      // used as a column key above — DataTable keys each header/body cell by
      // `String(column.key)`, so this action column needs a key distinct
      // from every other column's (the same reason PositionsTable.tsx's own
      // delete-action column keys off 'id' rather than reusing 'ticker').
      key: 'confidence_band',
      header: '',
      align: 'right',
      render: (row) => (
        <IconButton
          aria-label={`Remove ${row.ticker}`}
          size="small"
          onClick={() => setPendingRemove(row)}
        >
          <DeleteOutlineIcon fontSize="small" />
        </IconButton>
      ),
    },
  ]

  const handleConfirmRemove = () => {
    /* v8 ignore next 3 */
    if (!pendingRemove) {
      return
    }
    removeWatchlistItem.mutate(pendingRemove.ticker)
    setPendingRemove(null)
  }

  return (
    <Box>
      {removeWatchlistItem.isError && (
        <Box sx={{ mb: 2 }}>
          <ErrorState error={removeWatchlistItem.error} />
        </Box>
      )}
      <DataTable
        columns={columns}
        rows={items}
        getRowKey={(row) => row.ticker}
        emptyMessage="Your watchlist is empty. Add a ticker to get started."
        ariaLabel="Watchlist"
      />
      <ConfirmDialog
        open={pendingRemove !== null}
        title="Remove from watchlist"
        body={pendingRemove ? `Remove ${pendingRemove.ticker} from your watchlist?` : ''}
        confirmLabel="Remove"
        destructive
        onConfirm={handleConfirmRemove}
        onCancel={() => setPendingRemove(null)}
      />
    </Box>
  )
}
