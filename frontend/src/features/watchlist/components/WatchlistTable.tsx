import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlineOutlined'
import Box from '@mui/material/Box'
import IconButton from '@mui/material/IconButton'
import Skeleton from '@mui/material/Skeleton'
import { useMutationState } from '@tanstack/react-query'
import { useState } from 'react'
import type { WatchlistItemIn, WatchlistItemOut } from '../../../api/watchlist'
import ConfidenceGauge from '../../../components/common/ConfidenceGauge/ConfidenceGauge'
import ConfirmDialog from '../../../components/common/ConfirmDialog/ConfirmDialog'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import SignalBadge from '../../../components/common/SignalBadge/SignalBadge'
import TickerLink from '../../../components/common/TickerLink/TickerLink'
import { formatDate } from '../../../utils/format'
import { watchlistKeys } from '../hooks/queryKeys'
import { useRemoveWatchlistItem } from '../hooks/useRemoveWatchlistItem'

export interface WatchlistTableProps {
  items: WatchlistItemOut[]
}

/**
 * A synthetic row rendered in place of the real `WatchlistItemOut` while a
 * just-submitted `POST /api/watchlist` add for `ticker` is still in flight
 * (POST itself, then the invalidated GET refetch that actually recomputes
 * its signal — see useAddWatchlistItem's own doc comment). Every column's
 * `render` below swaps in an animated MUI `Skeleton` for this row instead of
 * its (nonexistent) real data, except the action column (keyed
 * `confidence_band`), which renders `null` — there is no remove action for a
 * row that isn't a real entry yet, so no Skeleton is shown there either. Used
 * directly inline here rather than promoted to its own `components/common/`
 * component — there's exactly one usage site and no shared behavior to
 * abstract beyond "render MUI's own `Skeleton`, sized per column" (unlike
 * SignalBadge/ConfidenceGauge, which encapsulate real domain-specific
 * coloring/formatting rules); see this task's `decisions` entry.
 */
type WatchlistRow = WatchlistItemOut & { isPendingSkeleton?: boolean }

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
 * composition (Frontend.md §3). A row's own Remove button is disabled while
 * `removeWatchlistItem` is pending *for that row's ticker specifically*
 * (`variables === row.ticker`, not just `isPending`) — otherwise a fast
 * double-click before the invalidated query refetches reopens the confirm
 * dialog and fires a second DELETE for an already-removed ticker, surfacing
 * a confusing false "Not found" error (frontend-watchlist-page-followups).
 *
 * Also renders a `WatchlistRow` skeleton placeholder for a ticker currently
 * being added (frontend-watchlist-add-skeleton): the pending ticker is read
 * directly off useAddWatchlistItem's shared mutation-cache entry via
 * `useMutationState` (keyed by `watchlistKeys.add`) rather than passed down
 * as a prop from AddTickerForm, which owns that mutation but is WatchlistTable's
 * *sibling* under WatchlistPage, not its parent — see this task's `decisions`
 * for why that was chosen over lifting the mutation to a common ancestor and
 * prop-drilling it to both. The skeleton row appears as soon as `mutate()` is
 * called (POST submit) and persists through both the POST and the GET
 * refetch it triggers, because that hook's own `onSuccess` awaits the
 * invalidated refetch — it disappears the instant either the mutation errors
 * (excluded by the `status: 'pending'` filter below, nothing further to
 * clean up since no skeleton row is itself a source of truth) or the
 * refetch completes and the ticker's real row is present in `items`. A
 * pending add for a ticker *already* in `items` (API.md's idempotent no-op
 * case) never gets a skeleton row in the first place — its real row is
 * already visible, so there is nothing to placeholder.
 */
export default function WatchlistTable({ items }: WatchlistTableProps) {
  const [pendingRemove, setPendingRemove] = useState<WatchlistItemOut | null>(null)
  const removeWatchlistItem = useRemoveWatchlistItem()

  const pendingAdds = useMutationState({
    filters: { mutationKey: watchlistKeys.add, status: 'pending' },
    select: (mutation) => ({
      ticker: (mutation.state.variables as WatchlistItemIn | undefined)?.ticker,
      // Stable for the lifetime of this mutation call (set once when
      // `mutate()` fires, unlike `new Date()` computed at render time, which
      // would drift by a few ms on every re-render) — see the sort-stability
      // note on the synthetic row below.
      submittedAt: mutation.state.submittedAt,
    }),
  })
  // Only one add mutation is ever in flight at a time in practice (its own
  // submit button is disabled/loading for the full duration, see
  // useAddWatchlistItem), but `.at(-1)` (most recently dispatched) is the
  // correct choice regardless, matching the "latest" convention
  // useMutationState's own docs use for reading a keyed mutation's state.
  const pendingAdd = pendingAdds.at(-1)
  const pendingTicker = pendingAdd?.ticker

  let rows: WatchlistRow[] = items
  if (
    pendingAdd !== undefined &&
    pendingTicker !== undefined &&
    !items.some((item) => item.ticker === pendingTicker)
  ) {
    rows = [
      ...items,
      {
        ticker: pendingTicker,
        // A real `WatchlistItemOut.added_at` sorts as an ISO timestamp;
        // `''` isn't one, and DataTable's sort comparator only treats
        // null/undefined as "missing" (always sorted last), so an empty
        // string was compared as an ordinary string and sorted before every
        // real date. That made the skeleton jump position the instant the
        // real row (with its now-newest `added_at`) replaced it under an
        // active sort. Using `submittedAt` (the mutation's own submit time,
        // always at or just before the server sets the real row's
        // `added_at` on that same POST) instead keeps the skeleton row
        // sorted where the real "just added" row is about to land — first
        // under a descending "Added" sort, last under ascending — so it
        // stays in place across the pending-to-real swap instead of jumping.
        // This column is never actually displayed for a pending row (its
        // `render` below always swaps in a Skeleton), so only its *sort*
        // value matters; see this task's `decisions` entry.
        added_at: new Date(pendingAdd.submittedAt).toISOString(),
        signal: null,
        confidence: null,
        confidence_band: null,
        isPendingSkeleton: true,
      },
    ]
  }

  const columns: DataTableColumn<WatchlistRow>[] = [
    {
      key: 'ticker',
      header: 'Ticker',
      sortable: true,
      render: (row) =>
        row.isPendingSkeleton ? (
          <Skeleton data-testid="watchlist-skeleton" variant="text" width={64} />
        ) : (
          <TickerLink ticker={row.ticker} />
        ),
    },
    {
      key: 'added_at',
      header: 'Added',
      sortable: true,
      render: (row) =>
        row.isPendingSkeleton ? (
          <Skeleton data-testid="watchlist-skeleton" variant="text" width={80} />
        ) : (
          formatDate(row.added_at)
        ),
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
      render: (row) =>
        row.isPendingSkeleton ? (
          <Skeleton
            data-testid="watchlist-skeleton"
            variant="rounded"
            width={56}
            height={24}
          />
        ) : row.signal == null ? (
          '—'
        ) : (
          <SignalBadge signal={row.signal} />
        ),
    },
    {
      key: 'confidence',
      header: 'Confidence',
      render: (row) =>
        row.isPendingSkeleton ? (
          <Skeleton
            data-testid="watchlist-skeleton"
            variant="rounded"
            width={96}
            height={24}
          />
        ) : row.confidence == null ? (
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
      render: (row) =>
        row.isPendingSkeleton ? null : (
          <IconButton
            aria-label={`Remove ${row.ticker}`}
            size="small"
            disabled={
              removeWatchlistItem.isPending &&
              removeWatchlistItem.variables === row.ticker
            }
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
        rows={rows}
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
