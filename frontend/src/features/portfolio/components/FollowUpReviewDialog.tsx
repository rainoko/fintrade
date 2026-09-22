import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogContentText from '@mui/material/DialogContentText'
import DialogTitle from '@mui/material/DialogTitle'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import { useState, type FormEvent } from 'react'
import type { ClosedTradeOut } from '../../../api/portfolio'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import { useRecordFollowUpReview } from '../hooks/useRecordFollowUpReview'

export interface FollowUpReviewDialogProps {
  /**
   * The trade being reviewed, or `null` when the dialog is closed — `open`
   * is derived from this rather than a separate boolean, so a caller can't
   * accidentally render the dialog open with nothing to review.
   */
  trade: ClosedTradeOut | null
  onClose: () => void
}

/**
 * Small form dialog recording Elder's mandatory two-months-later follow-up
 * review (ch. 59 Trade Journal Section E, docs/architecture/API.md's
 * `POST /api/portfolio/closed-trades/{trade_id}/follow-up-review`) for one
 * closed trade — reopening it with the benefit of hindsight and writing what
 * it teaches. `follow_up_notes` is required and validated non-blank
 * client-side before ever calling the mutation, mirroring the backend's own
 * `minLength: 1` on `FollowUpReviewIn.follow_up_notes` (API.md) rather than
 * relying solely on a round-trip 422.
 *
 * Feature component (not `common/`): it renders a `ClosedTradeOut` (ticker,
 * exit date) directly in its own copy, so it isn't a domain-agnostic
 * building block the way `common/ConfirmDialog` is.
 */
export default function FollowUpReviewDialog({ trade, onClose }: FollowUpReviewDialogProps) {
  const [notes, setNotes] = useState('')
  const [validationError, setValidationError] = useState<string | null>(null)
  const recordReview = useRecordFollowUpReview()

  // Reset local state whenever the dialog switches to a different trade (or
  // closes), so a second review doesn't start pre-filled with the previous
  // trade's notes or a stale error/pending state. Done during render (React's
  // documented "adjusting state when a prop changes" pattern), matching
  // AddPositionDialog's own `prevOpen` comparison.
  const [prevTradeId, setPrevTradeId] = useState<string | null>(trade?.id ?? null)
  if ((trade?.id ?? null) !== prevTradeId) {
    setPrevTradeId(trade?.id ?? null)
    setNotes('')
    setValidationError(null)
    recordReview.reset()
  }

  const handleClose = () => {
    onClose()
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    // The form only mounts while the Dialog is open, which only happens
    // while `trade !== null` (see the `open` prop below) -- unreachable
    // through the UI in practice, purely so TypeScript narrows `trade` from
    // `ClosedTradeOut | null` before `.id` is read below, same defensive
    // pattern as PositionsTable's own `pendingDelete` guard.
    /* v8 ignore next 3 */
    if (!trade) {
      return
    }
    const trimmed = notes.trim()
    if (!trimmed) {
      setValidationError('Follow-up notes are required.')
      return
    }
    setValidationError(null)
    recordReview.mutate(
      { tradeId: trade.id, followUpNotes: trimmed },
      { onSuccess: () => onClose() },
    )
  }

  return (
    <Dialog open={trade !== null} onClose={handleClose} fullWidth maxWidth="sm">
      <DialogTitle>Follow-Up Review{trade ? `: ${trade.ticker}` : ''}</DialogTitle>
      <form onSubmit={handleSubmit}>
        <DialogContent>
          <Stack spacing={2}>
            <DialogContentText>
              Reopen this trade with the benefit of hindsight (Elder ch. 59 Trade Journal
              Section E) — what does it teach you now, roughly two months later?
            </DialogContentText>
            {recordReview.isError && <ErrorState error={recordReview.error} />}
            <TextField
              label="Follow-up notes"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              error={Boolean(validationError)}
              helperText={validationError}
              multiline
              minRows={3}
              fullWidth
              autoFocus
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose} disabled={recordReview.isPending}>
            Cancel
          </Button>
          <Button type="submit" variant="contained" loading={recordReview.isPending}>
            Save Review
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  )
}
