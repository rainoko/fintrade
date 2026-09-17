import Link from '@mui/material/Link'
import { Link as RouterLink } from 'react-router-dom'
import type { PositionOut } from '../../../api/portfolio'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import PercentChange from '../../../components/common/PercentChange/PercentChange'
import { formatNullableCurrency } from '../../../utils/format'

export interface PositionsGlanceTableProps {
  positions: PositionOut[]
}

/**
 * Compact positions-at-a-glance table for the Dashboard: a trimmed-column
 * common/DataTable instance (ticker/quantity/price/unrealized P/L only, no
 * delete action) rather than the full PositionsTable — full position
 * management (add/delete, cost basis, entry date) stays on the Portfolio
 * page. The ticker cell links to /stocks/:ticker, giving the "quick path
 * into stock analysis" this page's description calls for directly from a
 * held position, alongside TickerSearchBox's free-text lookup.
 */
export default function PositionsGlanceTable({ positions }: PositionsGlanceTableProps) {
  const columns: DataTableColumn<PositionOut>[] = [
    {
      key: 'ticker',
      header: 'Ticker',
      sortable: true,
      render: (row) => (
        <Link component={RouterLink} to={`/stocks/${encodeURIComponent(row.ticker)}`}>
          {row.ticker}
        </Link>
      ),
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
