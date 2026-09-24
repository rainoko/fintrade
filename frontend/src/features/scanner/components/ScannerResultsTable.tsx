import AddIcon from '@mui/icons-material/Add'
import CheckIcon from '@mui/icons-material/Check'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutlined'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import CircularProgress from '@mui/material/CircularProgress'
import Tooltip from '@mui/material/Tooltip'
import { useState } from 'react'
import type { IBKRScannerResultOut } from '../../../api/ibkr'
import DataTable, { type DataTableColumn } from '../../../components/common/DataTable/DataTable'
import TickerLink from '../../../components/common/TickerLink/TickerLink'
import { useAddWatchlistItem } from '../../watchlist/hooks/useAddWatchlistItem'
import { scannerKeys } from '../hooks/queryKeys'

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
 * Passes `useAddWatchlistItem` its own `scannerKeys.addToWatchlist`
 * mutation key rather than that hook's default `watchlistKeys.add` (round-4
 * finding, PR #243) — `useMutation`'s cache is one app-wide store per
 * `QueryClient` keyed only by `mutationKey`, not scoped by dispatching
 * page/component, so leaving this on the shared default key meant a
 * still-pending Scanner-page add bled into `WatchlistTable`'s own
 * `useMutationState({ filters: { mutationKey: watchlistKeys.add } })` (used
 * there to render a pending-add skeleton row for *its own* AddTickerForm)
 * as a phantom skeleton row for a ticker the Watchlist page's own user never
 * touched, the moment that page was mounted before the Scanner-page add
 * settled. A distinct key keeps the two features' in-flight mutation state
 * from cross-contaminating while still sharing the one hook's `mutationFn`/
 * `onSuccess` behavior (this task's cross-feature-hook-reuse `decisions`
 * entry).
 *
 * Renders exactly one persistent `<Button>` element across every state
 * (idle / pending / error / added) rather than swapping between two
 * different element types (e.g. `<Button>` <-> `<IconButton>`) for the error
 * case — only its color/icon/label content changes. Round 3 swapped in a
 * separate `<IconButton>` on failure (to keep the row's height unchanged,
 * avoiding a round-2 regression where a full `common/ErrorState` block
 * inside a `<TableCell>` stretched every cell in that row to match) but that
 * swap unmounted the focused node and mounted a new one, dropping keyboard
 * focus to `document.body` — round 4 patched that transition with a
 * `useEffect`, but the *reverse* transition (retry succeeds, swapping back
 * from `<IconButton>` to `<Button>`) reintroduced the exact same bug on the
 * common, successful-retry path (round-4 review finding, PR #243). Using one
 * stable `<button>` DOM node throughout — MUI's `Tooltip` is likewise always
 * mounted around it, with an empty `title` when there's nothing to show,
 * rather than being conditionally rendered only for the error case — means
 * neither transition direction ever unmounts/remounts anything, so focus
 * survives automatically with no per-transition patching at all. The button
 * is intentionally never given the native `disabled` attribute, in any
 * state, including while pending: MUI's own `Button` `loading` prop sets
 * `disabled` internally (`disabled: disabled || loading`), and a
 * currently-focused element that becomes natively `disabled` is forced out
 * of the tab order and blurred to `document.body` by the browser itself
 * (confirmed against a real Chromium session, not just jsdom, which doesn't
 * reproduce this) — the exact same focus-loss symptom this whole redesign
 * exists to eliminate, just triggered by an attribute instead of an unmount.
 * A hand-rolled `CircularProgress` swapped in as the icon (instead of MUI's
 * `loading` prop) gives the same pending affordance without ever touching
 * `disabled`. This does mean the button stays clickable while a request is
 * already in flight (unlike the native-`disabled`-based approach, which also
 * blocks the browser's own click dispatch to a disabled element) — left
 * un-guarded deliberately rather than adding an `isPending` re-entrancy check
 * that a genuinely rapid double-click (two `fireEvent.click`s with no
 * intervening render, the same kind of true concurrency the two-different-
 * rows regression test below exercises) would bypass anyway, since
 * `mutate()`'s own state update isn't reflected in this closure's
 * `addWatchlistItem.isPending` until the next render: `POST /api/watchlist`
 * is an idempotent no-op on a ticker already on the watchlist (API.md), so a
 * duplicate in-flight request for the same row is harmless either way.
 *
 * A failed add's compact, in-place styling (error color + icon on the same
 * button, not `common/ErrorState`) keeps the row's height unchanged for the
 * same reason the round-3 fix did — `ErrorState` is a full page/section-scale
 * icon+heading+body block (see its own doc comment) meant to sit as a
 * sibling above a whole table (PositionsTable.tsx, WatchlistTable.tsx both
 * do exactly that for their own table-wide mutation errors), not inside one
 * of that table's cells.
 *
 * A visually-hidden `role="status"` element (always mounted, so its text
 * mutating on failure is a reliable live-region update regardless of mount
 * timing) announces the failure to assistive tech even for a user who has
 * already moved focus elsewhere (e.g. to check another row while this row's
 * request is still in flight) — `role="status"`, not `role="alert"`, so it
 * doesn't reintroduce the "full ErrorState block" landmark this component's
 * own tests assert is gone (see ScannerResultsTable.test.tsx's
 * `queryByRole('alert')` assertion).
 */
function ScannerAddToWatchlistButton({ ticker }: { ticker: string }) {
  const addWatchlistItem = useAddWatchlistItem({ mutationKey: scannerKeys.addToWatchlist })
  const [added, setAdded] = useState(false)

  const handleAdd = () =>
    addWatchlistItem.mutate({ ticker }, { onSuccess: () => setAdded(true) })

  const failureAnnouncement = addWatchlistItem.isError
    ? `Failed to add ${ticker} to watchlist: ${addWatchlistItem.error.detail}`
    : ''

  const label = addWatchlistItem.isError ? 'Retry' : added ? 'Added' : 'Add to watchlist'
  const icon = addWatchlistItem.isPending ? (
    <CircularProgress size={14} color="inherit" />
  ) : addWatchlistItem.isError ? (
    <ErrorOutlineIcon fontSize="small" />
  ) : added ? (
    <CheckIcon fontSize="small" />
  ) : (
    <AddIcon fontSize="small" />
  )

  return (
    <>
      {/* Always mounted (only its text content changes) so the live-region
          update is announced reliably rather than depending on the element
          itself being freshly inserted into the DOM. */}
      <Box
        role="status"
        sx={{
          position: 'absolute',
          width: 1,
          height: 1,
          padding: 0,
          margin: -1,
          overflow: 'hidden',
          clip: 'rect(0, 0, 0, 0)',
          whiteSpace: 'nowrap',
          border: 0,
        }}
      >
        {failureAnnouncement}
      </Box>
      {/* Tooltip is always mounted (empty title when there's nothing to show)
          so its child <Button> is never unmounted/remounted by a
          conditionally-rendered wrapper — see the doc comment above. */}
      <Tooltip
        title={addWatchlistItem.isError ? `${addWatchlistItem.error.detail} Click to retry.` : ''}
      >
        <span>
          <Button
            size="small"
            color={addWatchlistItem.isError ? 'error' : 'primary'}
            aria-label={
              addWatchlistItem.isError ? `Retry adding ${ticker} to watchlist` : undefined
            }
            startIcon={icon}
            onClick={handleAdd}
          >
            {label}
          </Button>
        </span>
      </Tooltip>
    </>
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
