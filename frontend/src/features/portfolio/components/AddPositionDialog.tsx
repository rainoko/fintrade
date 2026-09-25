import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import { useState, type FormEvent } from 'react'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import { isPositiveFinite } from '../../../utils/validation'
import { useAddPosition } from '../hooks/useAddPosition'
import { useGuardedDialogClose } from '../hooks/useGuardedDialogClose'

export interface AddPositionDialogProps {
  open: boolean
  onClose: () => void
  /**
   * Tickers already held, normalized to uppercase — used only to decide
   * which informational message to show after a successful submit (API.md's
   * merge-on-duplicate-ticker behavior), not for validation: the backend is
   * the sole source of truth for whether a merge actually happens.
   */
  existingTickers: string[]
}

interface FormState {
  ticker: string
  quantity: string
  avgCostBasis: string
  entryDate: string
  notes: string
}

interface FormErrors {
  ticker?: string
  quantity?: string
  avgCostBasis?: string
  entryDate?: string
}

const emptyForm: FormState = {
  ticker: '',
  quantity: '',
  avgCostBasis: '',
  entryDate: '',
  notes: '',
}

function validate(form: FormState): FormErrors {
  const errors: FormErrors = {}

  if (!form.ticker.trim()) {
    errors.ticker = 'Ticker is required.'
  }

  const quantity = Number(form.quantity)
  if (!form.quantity.trim() || !isPositiveFinite(quantity)) {
    errors.quantity = 'Quantity must be a positive number.'
  }

  const avgCostBasis = Number(form.avgCostBasis)
  if (!form.avgCostBasis.trim() || !isPositiveFinite(avgCostBasis)) {
    errors.avgCostBasis = 'Average cost basis must be a positive number.'
  }

  if (!form.entryDate.trim()) {
    errors.entryDate = 'Entry date is required.'
  }

  return errors
}

/**
 * Add-position form dialog (features/portfolio). Validates client-side
 * before ever calling useAddPosition, and — since a duplicate ticker merges
 * into the existing position rather than erroring (API.md) — surfaces which
 * of the two happened as an explicit success message instead of just
 * quietly closing, so the merge doesn't look like a silent no-op.
 */
export default function AddPositionDialog({
  open,
  onClose,
  existingTickers,
}: AddPositionDialogProps) {
  const [form, setForm] = useState<FormState>(emptyForm)
  const [errors, setErrors] = useState<FormErrors>({})
  const [successTicker, setSuccessTicker] = useState<string | null>(null)
  const [wasMerge, setWasMerge] = useState(false)
  const [prevOpen, setPrevOpen] = useState(open)
  const addPosition = useAddPosition()

  // Reset all local state whenever the dialog transitions to open, so a
  // second "Add Position" doesn't show the previous submission's values,
  // errors, or success message. Done during render (React's documented
  // "adjusting state when a prop changes" pattern) rather than in a
  // useEffect, which would set state after an extra committed render of the
  // stale (about-to-be-replaced) values.
  if (open !== prevOpen) {
    setPrevOpen(open)
    if (open) {
      setForm(emptyForm)
      setErrors({})
      setSuccessTicker(null)
      setWasMerge(false)
      addPosition.reset()
    }
  }

  const handleChange =
    (field: keyof FormState) => (event: { target: { value: string } }) => {
      setForm((current) => ({ ...current, [field]: event.target.value }))
    }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    const validationErrors = validate(form)
    setErrors(validationErrors)
    if (Object.keys(validationErrors).length > 0) {
      return
    }

    const normalizedTicker = form.ticker.trim().toUpperCase()
    const merging = existingTickers.includes(normalizedTicker)

    const trimmedNotes = form.notes.trim()

    addPosition.mutate(
      {
        ticker: normalizedTicker,
        quantity: Number(form.quantity),
        avg_cost_basis: Number(form.avgCostBasis),
        entry_date: form.entryDate,
        // Omitted entirely (rather than sent as an empty string) when blank
        // -- the backend already normalizes "" / whitespace-only to null
        // (PositionIn.entry_notes), but not sending the key at all keeps the
        // request body itself free of a pointless empty value.
        ...(trimmedNotes ? { entry_notes: trimmedNotes } : {}),
      },
      {
        onSuccess: () => {
          setWasMerge(merging)
          setSuccessTicker(normalizedTicker)
        },
      },
    )
  }

  const handleDone = () => {
    onClose()
  }

  // Guards against MUI's `Dialog` firing its own `onClose` on
  // Escape/backdrop-click mid-submit, regardless of the Cancel button's own
  // `disabled` state -- see `useGuardedDialogClose`'s own doc comment. This
  // gap was identical to (and predates) `IbkrPreloadDialog`'s own, fixed
  // there first in frontend-ibkr-portfolio-preload-followups #3; this task
  // (frontend-ibkr-portfolio-preload-followups-followups) closes it here too
  // via the shared hook extracted from that fix.
  const handleDialogClose = useGuardedDialogClose(onClose, addPosition.isPending)

  return (
    <Dialog open={open} onClose={handleDialogClose} fullWidth maxWidth="sm">
      <DialogTitle>Add Position</DialogTitle>
      {successTicker ? (
        <>
          <DialogContent>
            <Alert severity="success">
              {wasMerge
                ? `Merged into your existing ${successTicker} position (quantities summed, cost basis re-averaged).`
                : `Added ${successTicker} to your portfolio.`}
            </Alert>
          </DialogContent>
          <DialogActions>
            <Button onClick={handleDone} variant="contained">
              Done
            </Button>
          </DialogActions>
        </>
      ) : (
        <form onSubmit={handleSubmit}>
          <DialogContent>
            <Stack spacing={2}>
              {addPosition.isError && <ErrorState error={addPosition.error} />}
              <TextField
                label="Ticker"
                value={form.ticker}
                onChange={handleChange('ticker')}
                error={Boolean(errors.ticker)}
                helperText={errors.ticker}
                autoFocus
                fullWidth
              />
              <TextField
                label="Quantity"
                type="number"
                value={form.quantity}
                onChange={handleChange('quantity')}
                error={Boolean(errors.quantity)}
                helperText={errors.quantity}
                fullWidth
              />
              <TextField
                label="Avg Cost Basis"
                type="number"
                value={form.avgCostBasis}
                onChange={handleChange('avgCostBasis')}
                error={Boolean(errors.avgCostBasis)}
                helperText={errors.avgCostBasis}
                fullWidth
              />
              <TextField
                label="Entry Date"
                type="date"
                value={form.entryDate}
                onChange={handleChange('entryDate')}
                error={Boolean(errors.entryDate)}
                helperText={errors.entryDate}
                slotProps={{ inputLabel: { shrink: true } }}
                fullWidth
              />
              <TextField
                label="Notes (optional)"
                value={form.notes}
                onChange={handleChange('notes')}
                multiline
                minRows={2}
                fullWidth
                helperText="Why did you take this trade? (Elder ch. 59 Trade Journal Section A)"
              />
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={onClose} disabled={addPosition.isPending}>
              Cancel
            </Button>
            <Button type="submit" variant="contained" loading={addPosition.isPending}>
              Add Position
            </Button>
          </DialogActions>
        </form>
      )}
    </Dialog>
  )
}
