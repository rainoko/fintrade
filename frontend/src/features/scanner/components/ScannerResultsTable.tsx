import AddIcon from '@mui/icons-material/Add'
import CheckIcon from '@mui/icons-material/Check'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutlined'
import Button from '@mui/material/Button'
import IconButton from '@mui/material/IconButton'
import Tooltip from '@mui/material/Tooltip'
import { useState } from 'react'
import type { IBKRScannerResultOut } from '../../../api/ibkr'
import DataTable, { type DataTableColumn } from '../../../components/common/DataTable/DataTable'
import TickerLink from '../../../components/common/TickerLink/TickerLink'
import { useAddWatchlistItem } from '../../watchlist/hooks/useAddWatchlistItem'

export interface ScannerResultsTableProps {
  results: IBKRScannerResultOut[]
}

/**
 * Per-row "Add to watchlist" action. Calls `useAddWatchlistItem()` itself
 * (one `useMutation` instance per row) rather than sharing a single instance
 * across the whole table — a shared instance's `MutationObserver.mutate()`
 * detaches from whatever mutation it was previously watching as soon as a
 * *different* row's `mutate()` call reattaches it, so clicking "Add to
 * watchlist" on row A then row B before A's request resolves meant A's
 * `onSuccess` (and `isError`) never fired once A's own request did complete
 * — its button stayed stuck on "Add to watchlist" forever even though the
 * server-side add succeeded (see this task's `review.comments`, PR #243).
 * Giving each row its own hook call gives each row its own observer, so
 * concurrent adds on different rows resolve independently.
 *
 * A failed add renders a compact `Tooltip`-wrapped error icon button, not
 * `common/ErrorState` — ErrorState is a full page/section-scale icon+heading
 * +body block (see its own doc comment) meant to sit as a sibling above a
 * whole table (PositionsTable.tsx, WatchlistTable.tsx both do exactly that
 * for their own table-wide mutation errors), not inside one of that table's
 * cells — an HTML table row expands every cell to the tallest one, so
 * embedding ErrorState's block here broke this row's height relative to
 * every other row on a failed add (round 2 regression, PR #243). The icon
 * button doubles as a retry affordance (clicking it re-fires the same
 * `mutate()` call) and carries the failure detail as both its Tooltip title
 * and its `aria-label`, so it's discoverable without adding any visible
 * vertical space to the row.
 */
function ScannerAddToWatchlistButton({ ticker }: { ticker: string }) {
  const addWatchlistItem = useAddWatchlistItem()
  const [added, setAdded] = useState(false)

  const handleAdd = () =>
    addWatchlistItem.mutate({ ticker }, { onSuccess: () => setAdded(true) })

  if (addWatchlistItem.isError) {
    return (
      <Tooltip title={`${addWatchlistItem.error.detail} Click to retry.`}>
        <span>
          <IconButton
            aria-label={`Retry adding ${ticker} to watchlist`}
            size="small"
            color="error"
            disabled={addWatchlistItem.isPending}
            onClick={handleAdd}
          >
            <ErrorOutlineIcon fontSize="small" />
          </IconButton>
        </span>
      </Tooltip>
    )
  }

  return (
    <Button
      size="small"
      startIcon={added ? <CheckIcon fontSize="small" /> : <AddIcon fontSize="small" />}
      disabled={added}
      loading={addWatchlistItem.isPending}
      onClick={handleAdd}
    >
      {added ? 'Added' : 'Add to watchlist'}
    </Button>
  )
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
      render: (row) => (row.symbol ? <ScannerAddToWatchlistButton ticker={row.symbol} /> : null),
    },
  ]

  return (
    <DataTable
      columns={columns}
      rows={results}
      getRowKey={(row) => row.conid}
      emptyMessage="No matches for this scan."
      ariaLabel="Scanner results"
    />
  )
}
