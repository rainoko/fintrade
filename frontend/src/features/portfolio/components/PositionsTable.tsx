import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlineOutlined'
import Box from '@mui/material/Box'
import IconButton from '@mui/material/IconButton'
import Typography from '@mui/material/Typography'
import { useState } from 'react'
import type { PositionOut, RiskPosition } from '../../../api/portfolio'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
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
 * That same single shared mutation instance is also *why* two closes can
 * never actually overlap in flight, even though only the row Delete button
 * that started the in-flight close is disabled (the other rows' Delete
 * buttons stay clickable, and can open ClosePositionDialog for a different
 * position while the first close is still pending): `isPending` below is
 * passed into ClosePositionDialog *unscoped* -- the same
 * `deletePosition.isPending` regardless of which position the dialog is
 * currently open for -- so a dialog opened for a second position while the
 * first's close is still in flight already renders with its own Confirm
 * button disabled/loading, table-wide, and can't actually be confirmed
 * (`handleConfirmClose` never fires a second `deletePosition.mutate()`)
 * until the first close settles and `isPending` flips back to `false`. This
 * is a verified, tested invariant (see PositionsTable.test.tsx), not just an
 * assumption -- it's what keeps a second concurrent close from detaching
 * TanStack Query's mutation observer from the first one's still-tracked
 * error (which `belongsToOpenDialog` below wouldn't otherwise be able to
 * attribute correctly): scoping `isPending` per-row instead (e.g. for better
 * UX, since right now opening an unrelated position's dialog while another
 * closes shows its Confirm button confusingly already loading) would remove
 * this guard along with the confusing UX, so doing so must come with a
 * deliberate replacement guard against overlapping closes, not just a prop
 * change. See frontend-close-position-dialog-followups (PR #261 round-2
 * review).
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
 *
 * A close-position failure's `ErrorState` is scoped to whichever position it
 * actually belongs to (`deletePosition.variables?.id`), not just "the
 * currently open dialog": while ClosePositionDialog is open *for that same
 * position*, the error renders inside it (as `handleConfirmClose`'s own doc
 * comment describes); once the dialog has been dismissed for that position
 * (or was never reopened, or is now open for a *different* position — a
 * backdrop click can dismiss it while a DELETE is still in flight, see
 * `handleCancelClose`), the same error instead renders as a page-level
 * banner below, explicitly naming the position it belongs to. This is what
 * makes a background failure both (a) never invisible -- it's always shown
 * somewhere once it settles, dialog or banner -- and (b) never misattributed
 * to an unrelated, later-opened dialog for a different position. See this
 * task's `decisions` entry (PR #261 review) for the bug this fixes: the
 * dialog previously received `deletePosition.error` unconditionally, so a
 * stale error from a dismissed-while-pending close could render inside a
 * different position's dialog once reopened, or vanish entirely if none was
 * reopened.
 */
export default function PositionsTable({ positions }: PositionsTableProps) {
  const [pendingDelete, setPendingDelete] = useState<PositionOut | null>(null)
  const deletePosition = useDeletePosition()
  const riskQuery = usePortfolioRisk()

  // `deletePosition.error`/`.variables` describe whichever close attempt
  // last failed, which isn't necessarily the position the dialog is
  // currently open for (see this component's own doc comment above) --
  // `belongsToOpenDialog` is what decides whether that error renders inside
  // ClosePositionDialog itself or as the page-level banner below instead.
  const belongsToOpenDialog =
    pendingDelete !== null && deletePosition.variables?.id === pendingDelete.id
  const dialogCloseError = belongsToOpenDialog ? deletePosition.error : null
  const strayCloseError =
    !belongsToOpenDialog && deletePosition.isError ? deletePosition.error : null
  const strayCloseTicker = strayCloseError
    ? positions.find((position) => position.id === deletePosition.variables?.id)?.ticker
    : undefined

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
    const closedPositionId = pendingDelete.id
    deletePosition.mutate(
      { id: closedPositionId, ...values },
      // The dialog only closes on success -- an error leaves it open with
      // its own ErrorState visible (see ClosePositionDialog), so the user
      // can retry or cancel instead of the error appearing after the dialog
      // has already vanished.
      //
      // This onSuccess callback is bound to *this specific* mutate() call --
      // it isn't necessarily the one for whatever `pendingDelete` currently
      // holds by the time it fires. A backdrop click can dismiss this
      // dialog while this DELETE is still in flight (see
      // `handleCancelClose`), after which the user can open a *different*
      // position's dialog -- which shares this same `deletePosition`
      // instance's `isPending`, so its Confirm button stays disabled/loading
      // until this call settles. If this call's onSuccess cleared
      // `pendingDelete` unconditionally at that point, it would close the
      // second dialog out from under the user right as its own Confirm
      // button would have become clickable, silently discarding whatever
      // they'd already entered. The functional updater below scopes the
      // clear to only fire when `pendingDelete` still refers to the position
      // *this* mutation was for, no-op'ing otherwise. See this task's
      // `decisions` entry (frontend-close-position-dialog-followups-followups,
      // PR #285 review finding).
      {
        onSuccess: () =>
          setPendingDelete((current) =>
            current?.id === closedPositionId ? null : current,
          ),
      },
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
      {strayCloseError && (
        <Box sx={{ mb: 2 }}>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Failed to close {strayCloseTicker ?? 'a position'}:
          </Typography>
          <ErrorState error={strayCloseError} />
        </Box>
      )}
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
        error={dialogCloseError}
        onConfirm={handleConfirmClose}
        onCancel={handleCancelClose}
      />
    </Box>
  )
}
