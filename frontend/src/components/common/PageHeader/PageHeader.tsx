import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import type { ReactNode } from 'react'

export interface PageHeaderProps {
  /** Page title, rendered as the primary heading. */
  title: string
  /** Optional trailing slot for a page-level action (e.g. a button). */
  action?: ReactNode
}

/**
 * Domain-agnostic page-level heading used at the top of every route
 * (Dashboard/Portfolio/Stock Detail): a title plus an optional trailing
 * action slot (e.g. "Add Position"). Purely presentational — it takes no
 * domain data and does no fetching.
 */
export default function PageHeader({ title, action }: PageHeaderProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 2,
        mb: 3,
      }}
    >
      <Typography variant="h4" component="h1">
        {title}
      </Typography>
      {action && <Box>{action}</Box>}
    </Box>
  )
}
