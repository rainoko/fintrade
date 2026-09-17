import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'
import type { ReactNode } from 'react'

export interface RiskBreachBannerProps {
  /** Warning copy to display next to the icon — the only thing that varies between callers. */
  message: ReactNode
}

/**
 * Prominent 6%-rule-breach warning banner (icon + message, styled with
 * `theme.palette.riskBreach`), shared between RiskPanel and RiskSummaryCard
 * (Portfolio page and Dashboard, respectively) — both rendered the identical
 * Box/WarningAmberIcon/Typography markup with only the message text
 * differing (this task's finding from PR #67's review). Domain-agnostic
 * (just an icon + a caller-supplied message, no knowledge of "portfolio" or
 * "risk"), so it lives under `components/common/` rather than
 * `features/portfolio/` per Frontend.md §3's placement test — the callers
 * still own deciding *when* to render it and *what* it says.
 */
export default function RiskBreachBanner({ message }: RiskBreachBannerProps) {
  const theme = useTheme()

  return (
    <Box
      role="alert"
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1.5,
        p: 2,
        borderRadius: 1,
        border: '1px solid',
        borderColor: theme.palette.riskBreach.main,
        backgroundColor: theme.palette.riskBreach.background,
      }}
    >
      <WarningAmberIcon sx={{ color: theme.palette.riskBreach.main }} />
      <Typography sx={{ color: theme.palette.riskBreach.main, fontWeight: 700 }}>
        {message}
      </Typography>
    </Box>
  )
}
