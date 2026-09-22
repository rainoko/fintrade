import AddIcon from '@mui/icons-material/Add'
import CheckIcon from '@mui/icons-material/Check'
import Button from '@mui/material/Button'
import { useState } from 'react'
import type { IBKRScannerResultOut } from '../../../api/ibkr'
import DataTable, { type DataTableColumn } from '../../../components/common/DataTable/DataTable'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import TickerLink from '../../../components/common/TickerLink/TickerLink'
import { useAddWatchlistItem } from '../../watchlist/hooks/useAddWatchlistItem'

export interface ScannerResultsTableProps {
  results: IBKRScannerResultOut[]
}

/**
 * A completed scan's candidate list: symbol (linking to the existing ticker
 * detail view via the shared `common/TickerLink`, per this task's
 * description — "each hit's drill-down is the existing ticker detail view"),
 * company name, IBKR's own rank, and a per-row "Add to watchlist" action
 * (`POST /api/watchlist`).
 *
 * Reuses `features/watchlist/hooks/useAddWatchlistItem` directly rather than
 * a second add-to-watchlist mutation — it already encapsulates the correct
 * behavior (idempotent no-op on a duplicate, invalidates the watchlist query
 * on success) and duplicating that here would risk the two implementations
 * drifting apart. This is the first cross-feature hook import in the
 * codebase; unlike a component (where `pr-reviewer` explicitly checks
 * placement, Frontend.md §3), nothing about Frontend.md's rules restricts a
 * mutation hook — a thin wrapper over one `useMutation` call, no
 * feature-specific rendering — to only being called from within its own
 * feature folder. See this task's `decisions` entry.
 *
 * A result with no `symbol` (the field is nullable per IBKR's own response —
 * IBKRScannerResultOut's docstring) can't be linked to the ticker detail
 * view or added to the watchlist (`POST /api/watchlist` needs a ticker), so
 * it renders `#<conid>` in the symbol column and no action button in the
 * last column, rather than a broken link or an add button with nothing
 * to add.
 *
 * DataTable's own built-in `EmptyState` (via `emptyMessage`) handles the
 * "scan ran successfully but matched nothing" case — a genuinely different
 * outcome from `common/UnavailableState`'s "the scanner itself couldn't
 * run", which ScannerPanel renders instead of this component entirely when
 * `state !== 'available'` (see this task's checklist item testing both as
 * distinct states).
 */
export default function ScannerResultsTable({ results }: ScannerResultsTableProps) {
  const addWatchlistItem = useAddWatchlistItem()
  const [addedTickers, setAddedTickers] = useState<Set<string>>(new Set())

  const columns: DataTableColumn<IBKRScannerResultOut>[] = [
    {
      key: 'symbol',
      header: 'Symbol',
      sortable: true,
      render: (row) => (row.symbol ? <TickerLink ticker={row.symbol} /> : `#${row.conid}`),
    },
    {
      key: 'company_name',
      header: 'Company',
      sortable: true,
      render: (row) => row.company_name ?? '—',
    },
    {
      key: 'rank',
      header: 'Rank',
      sortable: true,
      render: (row) => row.rank ?? '—',
    },
    {
      // 'conid' is the only IBKRScannerResultOut field not otherwise used as
      // a column key above — DataTable keys each cell by `String(column.key)`,
      // so this action column needs a key distinct from every other column's.
      key: 'conid',
      header: '',
      align: 'right',
      render: (row) => {
        if (!row.symbol) {
          return null
        }
        const ticker = row.symbol
        const added = addedTickers.has(ticker)
        return (
          <Button
            size="small"
            startIcon={added ? <CheckIcon fontSize="small" /> : <AddIcon fontSize="small" />}
            disabled={added}
            loading={addWatchlistItem.isPending && addWatchlistItem.variables?.ticker === ticker}
            onClick={() =>
              addWatchlistItem.mutate(
                { ticker },
                { onSuccess: () => setAddedTickers((prev) => new Set(prev).add(ticker)) },
              )
            }
          >
            {added ? 'Added' : 'Add to watchlist'}
          </Button>
        )
      },
    },
  ]

  return (
    <>
      {addWatchlistItem.isError && <ErrorState error={addWatchlistItem.error} />}
      <DataTable
        columns={columns}
        rows={results}
        getRowKey={(row) => row.conid}
        emptyMessage="No matches for this scan."
        ariaLabel="Scanner results"
      />
    </>
  )
}
