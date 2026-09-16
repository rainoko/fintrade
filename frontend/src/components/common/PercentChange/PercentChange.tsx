import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'

export interface PercentChangeProps {
  /** Raw percentage value, e.g. 3.2 for +3.20%. Positive/negative/zero drive the color. */
  value: number
  /** Decimal places to display. Defaults to 2. */
  decimals?: number
}

/**
 * Colored +/-/zero percentage display, used for unrealized_pnl_pct and
 * similar percentage values across the app. Takes a plain number — no
 * knowledge of what the percentage represents.
 */
export default function PercentChange({ value, decimals = 2 }: PercentChangeProps) {
  const theme = useTheme()

  const color =
    value > 0
      ? theme.palette.success.main
      : value < 0
        ? theme.palette.error.main
        : theme.palette.text.secondary

  const sign = value > 0 ? '+' : ''
  const formatted = `${sign}${value.toFixed(decimals)}%`

  return (
    <Typography component="span" style={{ color, fontWeight: 600 }}>
      {formatted}
    </Typography>
  )
}
