import InboxOutlinedIcon from '@mui/icons-material/InboxOutlined'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import type { ReactNode } from 'react'

export interface EmptyStateProps {
  /** Short message explaining there's nothing to show, e.g. 'No positions yet'. */
  message: string
  /** Optional trailing action (e.g. an 'Add Position' button). */
  action?: ReactNode
}

/**
 * Generic "nothing to show" placeholder used by DataTable and any page-level
 * empty state (empty portfolio, no history, etc.). Takes only a message and
 * an optional action — no domain knowledge of what's empty.
 */
export default function EmptyState({ message, action }: EmptyStateProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 1.5,
        py: 6,
        px: 2,
        textAlign: 'center',
        color: 'text.secondary',
      }}
    >
      <InboxOutlinedIcon fontSize="large" color="disabled" />
      <Typography variant="body1" color="text.secondary">
        {message}
      </Typography>
      {action}
    </Box>
  )
}
