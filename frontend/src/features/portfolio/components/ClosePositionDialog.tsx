import Button from '@mui/material/Button'
import Checkbox from '@mui/material/Checkbox'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogContentText from '@mui/material/DialogContentText'
import DialogTitle from '@mui/material/DialogTitle'
import FormControl from '@mui/material/FormControl'
import FormControlLabel from '@mui/material/FormControlLabel'
import InputLabel from '@mui/material/InputLabel'
import MenuItem from '@mui/material/MenuItem'
import Select, { type SelectChangeEvent } from '@mui/material/Select'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import { useState, type FormEvent } from 'react'
import type { ApiError } from '../../../api/client'
import type { ExitReason, PositionOut } from '../../../api/portfolio'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import { isPositiveFinite } from '../../../utils/validation'
import { EXIT_REASON_LABELS } from '../exitReasonLabels'
import { useResetOnSubjectChange } from '../hooks/useResetOnSubjectChange'

export interface ClosePositionConfirmValues {
  exitReason: ExitReason
  /** Present only when the manual-exit override checkbox is checked, and always supplied together. */
  exitPrice?: number
  exitDate?: string
}

export interface ClosePositionDialogProps {
  /**
   * The position being closed, or `null` to keep the dialog closed — `open`
   * is derived from this rather than a separate boolean, mirroring
   * `FollowUpReviewDialog`/`TradeApgarDialog`'s own "the subject drives
   * openness" pattern, so a caller can't accidentally render the dialog open
   * with nothing to close.
   */
  position: PositionOut | null
  isPending: boolean
  /**
   * The close attempt's error, or `null` when there isn't one -- a single
   * nullable field rather than a separate `isError` boolean alongside it,
   * so there's no way for the two to disagree (unlike TanStack Query's own
   * `isError`/`error` pair, which are two independent fields on the same
   * mutation object).
   */
  error: ApiError | null
  onConfirm: (values: ClosePositionConfirmValues) => void
  onCancel: () => void
}

interface FormState {
  exitReason: ExitReason
  useManualOverride: boolean
  exitPrice: string
  exitDate: string
}

interface FormErrors {
  exitPrice?: string
  exitDate?: string
}

const emptyForm: FormState = {
  exitReason: 'unspecified',
  useManualOverride: false,
  exitPrice: '',
  exitDate: '',
}

// Reuses TradeJournalPanel's own exit-reason label source of truth
// (exitReasonLabels.ts) for this <select>'s options instead of a second,
// independently-maintained label list — `Object.entries` preserves the
// object's declared insertion order, so the option order here matches the
// order that file already documents them in.
const EXIT_REASON_OPTIONS: Array<{ value: ExitReason; label: string }> = Object.entries(
  EXIT_REASON_LABELS,
).map(([value, label]) => ({ value: value as ExitReason, label }))

function validate(form: FormState, entryDate: string): FormErrors {
  if (!form.useManualOverride) {
    return {}
  }

  const errors: FormErrors = {}

  const exitPrice = Number(form.exitPrice)
  if (!form.exitPrice.trim() || !isPositiveFinite(exitPrice)) {
    errors.exitPrice = 'Exit price must be a positive number.'
  }

  if (!form.exitDate.trim()) {
    errors.exitDate = 'Exit date is required.'
  } else if (form.exitDate < entryDate) {
    errors.exitDate = `Exit date must not be before the entry date (${entryDate}).`
  }

  return errors
}

/**
 * Close-position confirm dialog (features/portfolio) — replaces the bare
 * `common/ConfirmDialog` PositionsTable used to show, adding the
 * `exit_reason` selector the backend endpoint has always accepted but no UI
 * ever surfaced, plus the optional manual exit price/date override
 * (backend-close-position-manual-exit) for backfilling a trade that already
 * happened in the past. See docs/ideas.md's "No manual 'Sell / Close
 * position' form" entry for the full motivation.
 *
 * Deliberately does *not* own its `useDeletePosition()` mutation itself
 * (unlike AddPositionDialog/FollowUpReviewDialog/TradeApgarDialog, each of
 * which owns its own mutation) — `isPending`/`error`/`onConfirm` are lifted
 * into PositionsTable instead, so the mutation's pending state
 * can also disable that specific row's own Delete icon button outside this
 * dialog (the double-click-race guard PositionsTable's own doc comment
 * describes) using the *same* mutation instance. Two independent
 * `useDeletePosition()` calls wouldn't share that pending state. See this
 * task's `decisions` entry.
 *
 * Feature component (not `common/`): it renders `ExitReason`/`PositionOut`
 * directly, both portfolio domain concepts — same placement call
 * AddPositionDialog/FollowUpReviewDialog/TradeApgarDialog already made for
 * themselves.
 */
export default function ClosePositionDialog({
  position,
  isPending,
  error,
  onConfirm,
  onCancel,
}: ClosePositionDialogProps) {
  const [form, setForm] = useState<FormState>(emptyForm)
  const [errors, setErrors] = useState<FormErrors>({})

  // Reset local form state whenever the dialog switches to a different
  // position (or closes), so closing a second position doesn't start
  // pre-filled with the first one's exit reason/manual override values —
  // same shared pattern FollowUpReviewDialog/TradeApgarDialog use for their
  // own subjects.
  useResetOnSubjectChange(position?.id ?? null, () => {
    setForm(emptyForm)
    setErrors({})
  })

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    // The form only mounts while the Dialog is open, which only happens
    // while `position !== null` (see the `open` prop below) -- unreachable
    // through the UI in practice, purely so TypeScript narrows `position`
    // before `.entry_date` is read below, same defensive pattern as
    // FollowUpReviewDialog/TradeApgarDialog's own subject guards.
    /* v8 ignore next 3 */
    if (!position) {
      return
    }

    const validationErrors = validate(form, position.entry_date)
    setErrors(validationErrors)
    if (Object.keys(validationErrors).length > 0) {
      return
    }

    onConfirm({
      exitReason: form.exitReason,
      ...(form.useManualOverride
        ? { exitPrice: Number(form.exitPrice), exitDate: form.exitDate }
        : {}),
    })
  }

  return (
    <Dialog open={position !== null} onClose={onCancel} fullWidth maxWidth="sm">
      <DialogTitle>Close Position{position ? `: ${position.ticker}` : ''}</DialogTitle>
      <form onSubmit={handleSubmit}>
        <DialogContent>
          <Stack spacing={2}>
            <DialogContentText>
              {position
                ? `Close ${position.ticker} (${position.quantity} shares)? This cannot be undone.`
                : ''}
            </DialogContentText>
            {error && <ErrorState error={error} />}
            <FormControl fullWidth>
              <InputLabel id="close-position-exit-reason-label">Exit reason</InputLabel>
              <Select
                labelId="close-position-exit-reason-label"
                label="Exit reason"
                value={form.exitReason}
                onChange={(event: SelectChangeEvent) =>
                  setForm((current) => ({
                    ...current,
                    exitReason: event.target.value as ExitReason,
                  }))
                }
              >
                {EXIT_REASON_OPTIONS.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControlLabel
              control={
                <Checkbox
                  checked={form.useManualOverride}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      useManualOverride: event.target.checked,
                    }))
                  }
                />
              }
              label="Backfill a historical exit price/date instead of today's live price"
            />
            {form.useManualOverride && (
              <>
                <TextField
                  label="Exit Price"
                  type="number"
                  value={form.exitPrice}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, exitPrice: event.target.value }))
                  }
                  error={Boolean(errors.exitPrice)}
                  helperText={errors.exitPrice}
                  fullWidth
                />
                <TextField
                  label="Exit Date"
                  type="date"
                  value={form.exitDate}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, exitDate: event.target.value }))
                  }
                  error={Boolean(errors.exitDate)}
                  helperText={errors.exitDate}
                  slotProps={{ inputLabel: { shrink: true } }}
                  fullWidth
                />
              </>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={onCancel} disabled={isPending}>
            Cancel
          </Button>
          <Button type="submit" variant="contained" color="error" loading={isPending}>
            Close Position
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  )
}
