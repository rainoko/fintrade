import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'

export interface RiskPercentProps {
  /** Raw percentage value, e.g. 1.8 for "1.80%". Always non-negative — a risk-exposure magnitude, not a gain/loss. */
  value: number
  /** Whether this value breaches the caller's own risk rule (e.g. the 2% rule) — drives whether it renders as a warning. */
  breached?: boolean
  /** Decimal places to display. Defaults to 2. */
  decimals?: number
}

/**
 * Colored risk-magnitude percentage display, for values like
 * `RiskPosition.position_risk_pct` where higher is worse and the value is
 * never negative — unlike common/PercentChange (gain/loss, green-for-
 * positive), which reusing here would render a breaching row's own risk
 * number in green, working against its red row highlight (this task's
 * finding from PR #66's review). No `+` sign (there's no "gain" reading of a
 * risk percentage) and no green case: renders in `riskBreach.main` when
 * `breached`, or a neutral/muted color otherwise — see this task's
 * `decisions` entry for the alternatives considered.
 */
export default function RiskPercent({ value, breached = false, decimals = 2 }: RiskPercentProps) {
  const theme = useTheme()

  const color = breached ? theme.palette.riskBreach.main : theme.palette.text.secondary
  const formatted = `${value.toFixed(decimals)}%`

  return (
    <Typography component="span" style={{ color, fontWeight: breached ? 700 : 400 }}>
      {formatted}
    </Typography>
  )
}
