import AcUnitIcon from '@mui/icons-material/AcUnit'
import ParkIcon from '@mui/icons-material/Park'
import SpaIcon from '@mui/icons-material/Spa'
import WbSunnyIcon from '@mui/icons-material/WbSunny'
import Chip from '@mui/material/Chip'
import { useTheme } from '@mui/material/styles'

export type Season = 'Spring' | 'Summer' | 'Autumn' | 'Winter'

export interface SeasonBadgeProps {
  season: Season
}

/**
 * Colored, iconed chip for an Indicator Season value (docs/Analyse.md row
 * 12, Elder ch. 32 "Time"). Takes only a plain string-union prop and no
 * domain knowledge of how the season was derived -- same domain-agnostic
 * test `common/SignalBadge` already applies (Frontend.md §3) -- so it lives
 * in `components/common/` rather than `features/stocks/`.
 *
 * Deliberately styled to read as *not* a BUY/SELL/HOLD signal, per the
 * frontend-indicator-seasons-badge task: an `outlined` (not filled) Chip,
 * its own four-color `theme.palette.season.*` set (never
 * `theme.palette.signal.*`), plus a season icon that a signal chip never
 * has -- three independent visual differences from `SignalBadge`, not just
 * one, since a filled Chip using signal-adjacent colors is exactly what a
 * user already associates with "this is the trading signal."
 */
export default function SeasonBadge({ season }: SeasonBadgeProps) {
  const theme = useTheme()

  const color =
    season === 'Spring'
      ? theme.palette.season.spring
      : season === 'Summer'
        ? theme.palette.season.summer
        : season === 'Autumn'
          ? theme.palette.season.autumn
          : theme.palette.season.winter

  const Icon =
    season === 'Spring'
      ? SpaIcon
      : season === 'Summer'
        ? WbSunnyIcon
        : season === 'Autumn'
          ? ParkIcon
          : AcUnitIcon

  return (
    <Chip
      label={season}
      data-testid="season-badge"
      icon={<Icon fontSize="small" style={{ color }} />}
      variant="outlined"
      size="small"
      style={{
        borderColor: color,
        color,
        fontWeight: 700,
      }}
    />
  )
}
