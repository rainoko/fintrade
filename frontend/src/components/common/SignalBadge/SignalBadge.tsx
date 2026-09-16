import Chip from '@mui/material/Chip'
import { useTheme } from '@mui/material/styles'

export type Signal = 'BUY' | 'SELL' | 'HOLD'

export interface SignalBadgeProps {
  signal: Signal
}

/**
 * Colored chip for a BUY/SELL/HOLD signal value (docs/Analyse.md's Triple
 * Screen output). Takes a plain string-union prop only — it doesn't fetch or
 * know how the signal was derived, matching Frontend.md §3's example of a
 * domain-agnostic common/ component.
 */
export default function SignalBadge({ signal }: SignalBadgeProps) {
  const theme = useTheme()

  const color =
    signal === 'BUY'
      ? theme.palette.signal.buy
      : signal === 'SELL'
        ? theme.palette.signal.sell
        : theme.palette.signal.hold

  return (
    <Chip
      label={signal}
      data-testid="signal-badge"
      style={{
        backgroundColor: color,
        color: theme.palette.getContrastText(color),
        fontWeight: 700,
      }}
      size="small"
    />
  )
}
