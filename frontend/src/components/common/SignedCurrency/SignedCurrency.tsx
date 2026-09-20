import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'
import { formatCurrency } from '../../../utils/format'
import { signColor } from '../../../utils/signColor'

export interface SignedCurrencyProps {
  /** Raw dollar amount, e.g. 201.0 for "+$201.00" or -84.5 for "-$84.50". Positive/negative/zero drive the color. */
  value: number
}

/**
 * Colored +/-/zero dollar-amount display — the currency counterpart to
 * `common/PercentChange`, for values like `ClosedTradeOut.realized_pnl`
 * where the sign (not just the magnitude) is the point. Domain-agnostic:
 * takes a plain number, no knowledge of what the amount represents.
 *
 * `formatCurrency` already renders a leading `-` for a negative value (it's
 * a straight `toLocaleString(..., {style:'currency'})` call) — this
 * component only adds the leading `+` for a positive value and the
 * success/error/neutral coloring on top, mirroring PercentChange's own
 * sign-handling split (PercentChange builds its own `+`/no-sign string
 * directly since `toFixed` never adds one; formatCurrency here already
 * supplies the `-`, so only `+` needs adding explicitly).
 */
export default function SignedCurrency({ value }: SignedCurrencyProps) {
  const theme = useTheme()

  const color = signColor(theme, value)

  const sign = value > 0 ? '+' : ''
  const formatted = `${sign}${formatCurrency(value)}`

  return (
    <Typography component="span" style={{ color, fontWeight: 600 }}>
      {formatted}
    </Typography>
  )
}
