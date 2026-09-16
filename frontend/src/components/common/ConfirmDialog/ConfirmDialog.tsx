import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogContentText from '@mui/material/DialogContentText'
import DialogTitle from '@mui/material/DialogTitle'
import type { ReactNode } from 'react'

export interface ConfirmDialogProps {
  open: boolean
  title: string
  /** Body copy, e.g. 'Delete this position? This cannot be undone.' */
  body: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  /** Whether the confirm action is destructive (renders in the error color). Defaults to false. */
  destructive?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/**
 * Generic confirm/cancel modal (used e.g. to confirm deleting a portfolio
 * position). Takes only presentation props and callbacks — no domain
 * knowledge of what's being confirmed.
 */
export default function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  destructive = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <Dialog open={open} onClose={onCancel} aria-labelledby="confirm-dialog-title">
      <DialogTitle id="confirm-dialog-title">{title}</DialogTitle>
      <DialogContent>
        <DialogContentText component="div">{body}</DialogContentText>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel}>{cancelLabel}</Button>
        <Button
          onClick={onConfirm}
          color={destructive ? 'error' : 'primary'}
          variant="contained"
        >
          {confirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
