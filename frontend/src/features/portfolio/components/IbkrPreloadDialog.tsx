import Button from '@mui/material/Button'
import Checkbox from '@mui/material/Checkbox'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableContainer from '@mui/material/TableContainer'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import Typography from '@mui/material/Typography'
import { useState } from 'react'
import type {
  IBKRPortfolioPreloadImportedPositionOut,
  IBKRPortfolioPreviewPositionOut,
} from '../../../api/ibkr'
import type { PositionOut } from '../../../api/portfolio'
import DataTable, { type DataTableColumn } from '../../../components/common/DataTable/DataTable'
import EmptyState from '../../../components/common/EmptyState/EmptyState'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import UnavailableState from '../../../components/common/UnavailableState/UnavailableState'
import { formatCurrency, formatNullableCurrency } from '../../../utils/format'
import { useIbkrPortfolioPreload } from '../hooks/useIbkrPortfolioPreload'
import { useIbkrPortfolioPreview } from '../hooks/useIbkrPortfolioPreview'
import { useOnValueChange } from '../hooks/useResetOnSubjectChange'

export interface IbkrPreloadDialogProps {
  open: boolean
  onClose: () => void
  /**
   * Positions already held locally, used only to resolve which local
   * position (id, quantity, avg cost) a conflicting IBKR ticker actually
   * refers to -- `GET /api/ibkr/portfolio-preview`'s own response only
   * carries the IBKR side of a conflict (`IBKRPortfolioPreviewPositionOut`
   * has no local position id at all). `PortfolioPage` already holds this
   * from its own `usePortfolio()` call, so it's passed down rather than this
   * dialog fetching it a second time.
   */
  existingPositions: PositionOut[]
}

interface ConflictRow {
  ibkr: IBKRPortfolioPreviewPositionOut
  local: PositionOut | undefined
}

/**
 * Review-and-confirm dialog for the "Preload from IBKR" flow
 * (frontend-ibkr-portfolio-preload): fetches `GET /api/ibkr/portfolio-preview`
 * while open, shows which fetched IBKR positions will be imported as-is and
 * which conflict with an existing local position, lets the user choose which
 * conflicting local positions to delete, and on confirm deletes exactly
 * those chosen positions before calling `POST /api/ibkr/portfolio-preload` —
 * matching the backend's required delete-then-import ordering
 * (`useIbkrPortfolioPreload`). Never presents this as a merge/update of a
 * position the user didn't choose to delete (backend-ibkr-portfolio-preload's
 * requirement 3) — a still-conflicting, not-selected ticker's checkbox
 * simply stays unchecked and that position is left untouched.
 *
 * The conflicting-tickers table is a hand-rolled MUI `Table`, not
 * `common/DataTable`: each row mixes two distinct data sources (the IBKR
 * side and the resolved local side), and `DataTableColumn<T>.key` must be a
 * real, distinct `keyof T` per column (it doubles as each cell's React key,
 * see PositionsTable.tsx's own synthetic-column precedent) — this row shape
 * only has two real fields (`ibkr`/`local`) but needs four visually distinct
 * columns, which would force reusing the same two keys twice each and
 * collide as duplicate React keys within a row. The non-conflicting and
 * imported-positions tables below have no such mixed-source shape (a single
 * `IBKRPortfolioPreviewPositionOut`/`IBKRPortfolioPreloadImportedPositionOut`
 * per row, four genuinely distinct fields), so those still use
 * `common/DataTable` — this task's `decisions` entry.
 *
 * Feature component (not `common/`): every prop/rendering decision here is
 * portfolio- and IBKR-domain-specific (a "position", a "conflict", an IBKR
 * ticker import) — same placement call `AddPositionDialog`/
 * `ClosePositionDialog` already made for themselves (Frontend.md §3). No new
 * `components/common/` component was needed for this task — the review
 * screen is built entirely from existing common building blocks
 * (`DataTable`, `EmptyState`, `LoadingState`, `ErrorState`,
 * `UnavailableState`) — so there's no new Storybook story to add either. See
 * this task's `decisions` entry.
 */
export default function IbkrPreloadDialog({
  open,
  onClose,
  existingPositions,
}: IbkrPreloadDialogProps) {
  const [selectedDeleteIds, setSelectedDeleteIds] = useState<Set<string>>(new Set())
  const previewQuery = useIbkrPortfolioPreview(open)
  const preloadMutation = useIbkrPortfolioPreload()

  // Reset local selection/mutation state whenever the dialog transitions to
  // open, so a second "Preload from IBKR" doesn't start pre-checked with the
  // previous review's selections or show a stale success/error from an
  // earlier attempt — same pattern AddPositionDialog/ClosePositionDialog use
  // for their own local state, generalized via useOnValueChange (this hook's
  // existing `open`/`null`-transition shape works for a plain boolean too).
  useOnValueChange(open, (isOpen) => {
    if (isOpen) {
      setSelectedDeleteIds(new Set())
      preloadMutation.reset()
    }
  })

  const toggleSelected = (id: string) => {
    setSelectedDeleteIds((current) => {
      const next = new Set(current)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const handleConfirm = () => {
    preloadMutation.mutate({ deleteIds: Array.from(selectedDeleteIds) })
  }

  const handleDone = () => {
    onClose()
  }

  const allPositions = previewQuery.data?.positions ?? []
  const nonConflicting = allPositions.filter(
    (position) => !position.conflicts_with_existing_position,
  )
  const conflictRows: ConflictRow[] = allPositions
    .filter((position) => position.conflicts_with_existing_position)
    .map((position) => ({
      ibkr: position,
      local: existingPositions.find((existing) => existing.ticker === position.ticker),
    }))

  const importCount = nonConflicting.length + selectedDeleteIds.size
  const hasNoPositions = allPositions.length === 0
  const isAvailable = previewQuery.data?.state === 'available'

  const nonConflictingColumns: DataTableColumn<IBKRPortfolioPreviewPositionOut>[] = [
    { key: 'ticker', header: 'Ticker' },
    { key: 'quantity', header: 'Quantity', align: 'right' },
    {
      key: 'avg_cost',
      header: 'Avg Cost',
      align: 'right',
      render: (row) => formatNullableCurrency(row.avg_cost),
    },
  ]

  const importedColumns: DataTableColumn<IBKRPortfolioPreloadImportedPositionOut>[] = [
    { key: 'ticker', header: 'Ticker' },
    { key: 'quantity', header: 'Quantity', align: 'right' },
    {
      key: 'avg_cost_basis',
      header: 'Avg Cost',
      align: 'right',
      render: (row) => formatCurrency(row.avg_cost_basis),
    },
    { key: 'entry_date', header: 'Entry Date' },
  ]

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>Preload from IBKR</DialogTitle>
      {preloadMutation.isSuccess ? (
        <>
          <DialogContent>
            <Stack spacing={2}>
              <Typography>
                Imported {preloadMutation.data.imported?.length ?? 0} position
                {(preloadMutation.data.imported?.length ?? 0) === 1 ? '' : 's'} from IBKR.
              </Typography>
              <DataTable
                columns={importedColumns}
                rows={preloadMutation.data.imported ?? []}
                getRowKey={(row) => row.ticker}
                emptyMessage="No positions were imported."
                ariaLabel="Imported IBKR positions"
              />
              {preloadMutation.data.skipped_conflicting_tickers &&
                preloadMutation.data.skipped_conflicting_tickers.length > 0 && (
                  <Typography variant="body2" color="text.secondary">
                    Still skipped as conflicting:{' '}
                    {preloadMutation.data.skipped_conflicting_tickers.join(', ')}
                  </Typography>
                )}
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={handleDone} variant="contained">
              Done
            </Button>
          </DialogActions>
        </>
      ) : (
        <>
          <DialogContent>
            <Stack spacing={2}>
              {previewQuery.isLoading && <LoadingState message="Fetching IBKR positions..." />}
              {previewQuery.isError && <ErrorState error={previewQuery.error} />}
              {previewQuery.data && !isAvailable && (
                <UnavailableState
                  heading="IBKR unavailable"
                  message={
                    previewQuery.data.detail ?? 'The IBKR integration is not available right now.'
                  }
                />
              )}
              {previewQuery.data && isAvailable && hasNoPositions && (
                <EmptyState message="No IBKR positions are available to preload right now." />
              )}
              {previewQuery.data && isAvailable && !hasNoPositions && (
                <>
                  {preloadMutation.isError && (
                    <Stack spacing={1}>
                      <ErrorState error={preloadMutation.error} />
                      <Typography variant="body2" color="text.secondary">
                        Any positions already deleted before this failure remain deleted — check
                        the positions table before retrying.
                      </Typography>
                    </Stack>
                  )}
                  <Typography variant="subtitle1">
                    New positions to import ({nonConflicting.length})
                  </Typography>
                  <DataTable
                    columns={nonConflictingColumns}
                    rows={nonConflicting}
                    getRowKey={(row) => row.conid}
                    emptyMessage="No new IBKR positions to import right now."
                    ariaLabel="Non-conflicting IBKR positions"
                  />
                  <Typography variant="subtitle1">
                    Conflicting tickers ({conflictRows.length})
                  </Typography>
                  {conflictRows.length === 0 ? (
                    <EmptyState message="No conflicts — every fetched IBKR position can be imported directly." />
                  ) : (
                    <TableContainer component={Paper} variant="outlined">
                      <Table aria-label="Conflicting IBKR positions">
                        <TableHead>
                          <TableRow>
                            <TableCell>Delete existing?</TableCell>
                            <TableCell>Ticker</TableCell>
                            <TableCell align="right">Existing (local)</TableCell>
                            <TableCell align="right">Incoming (IBKR)</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {conflictRows.map((row) => (
                            <TableRow key={row.ibkr.conid}>
                              <TableCell>
                                {row.local ? (
                                  <Checkbox
                                    checked={selectedDeleteIds.has(row.local.id)}
                                    onChange={() => row.local && toggleSelected(row.local.id)}
                                    slotProps={{
                                      input: {
                                        'aria-label': `Delete existing ${row.ibkr.ticker} position`,
                                      },
                                    }}
                                  />
                                ) : (
                                  '—'
                                )}
                              </TableCell>
                              <TableCell>{row.ibkr.ticker}</TableCell>
                              <TableCell align="right">
                                {row.local
                                  ? `${row.local.quantity} @ ${formatCurrency(row.local.avg_cost_basis)}`
                                  : 'Not found locally'}
                              </TableCell>
                              <TableCell align="right">
                                {row.ibkr.quantity} @ {formatNullableCurrency(row.ibkr.avg_cost)}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  )}
                  <Typography variant="body2" color="text.secondary">
                    Confirming will delete {selectedDeleteIds.size} selected existing position
                    {selectedDeleteIds.size === 1 ? '' : 's'}, then import {importCount} IBKR
                    position{importCount === 1 ? '' : 's'}. A conflicting position you don't select
                    stays exactly as it is — it is never merged or updated.
                  </Typography>
                </>
              )}
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={onClose} disabled={preloadMutation.isPending}>
              Cancel
            </Button>
            {isAvailable && !hasNoPositions && (
              <Button
                onClick={handleConfirm}
                variant="contained"
                disabled={importCount === 0}
                loading={preloadMutation.isPending}
              >
                Import {importCount} position{importCount === 1 ? '' : 's'}
              </Button>
            )}
          </DialogActions>
        </>
      )}
    </Dialog>
  )
}
