import type { PositionOut } from '../../../api/portfolio'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import PercentChange from '../../../components/common/PercentChange/PercentChange'
import SignalBadge from '../../../components/common/SignalBadge/SignalBadge'
import TickerLink from '../../../components/common/TickerLink/TickerLink'
import { formatNullableCurrency } from '../../../utils/format'

export interface PositionsGlanceTableProps {
  positions: PositionOut[]
}

/**
 * Compact positions-at-a-glance table for the Dashboard: a trimmed-column
 * common/DataTable instance (ticker/quantity/price/unrealized P/L/signal, no
 * delete action) rather than the full PositionsTable — full position
 * management (add/delete, cost basis, entry date) stays on the Portfolio
 * page. The ticker cell links to /stocks/:ticker, giving the "quick path
 * into stock analysis" this page's description calls for directly from a
 * held position, alongside TickerSearchBox's free-text lookup. Ticker cell
 * uses the shared common/TickerLink component (frontend-ticker-link) rather
 * than its own inline Link, so this and every other ticker-displaying table
 * (PositionsTable, RiskPanel, WatchlistTable) share one implementation. The
 * Signal column reuses the exact common/SignalBadge + '—' null-fallback
 * pattern WatchlistTable established (frontend-lists-show-signal).
 */
export default function PositionsGlanceTable({ positions }: PositionsGlanceTableProps) {
  const columns: DataTableColumn<PositionOut>[] = [
    {
      key: 'ticker',
      header: 'Ticker',
      sortable: true,
      render: (row) => <TickerLink ticker={row.ticker} />,
    },
    { key: 'quantity', header: 'Quantity', sortable: true, align: 'right' },
    {
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
      key: 'signal',
      header: 'Signal',
      render: (row) => (row.signal == null ? '—' : <SignalBadge signal={row.signal} />),
    },
  ]

  return (
    <DataTable
      columns={columns}
      rows={positions}
      getRowKey={(row) => row.id}
      emptyMessage="No positions yet. Add one from the Portfolio page to get started."
      ariaLabel="Positions at a glance"
    />
  )
}
