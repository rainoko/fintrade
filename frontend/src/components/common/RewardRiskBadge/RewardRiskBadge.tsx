import WarningAmberIcon from '@mui/icons-material/WarningAmberOutlined'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'

export interface RewardRiskBadgeProps {
  /**
   * The reward:risk ratio itself (e.g. `2.4` for "2.4:1"), or `null` when
   * it's undefined (e.g. `ProfitTargetOut.reward_risk_ratio` is null
   * whenever the underlying stop distance is <= 0). Renders as "n/a" rather
   * than a fabricated number.
   */
  ratio: number | null
  /**
   * Whether `ratio` clears the caller's own minimum bar -- e.g. Elder's
   * explicit 2:1 profit-target rule ("it seldom pays to risk a dollar to
   * make a dollar", docs/Analyse.md §7). Always `false` when `ratio` is
   * `null`, matching `ProfitTargetOut.meets_minimum_reward_risk`'s own
   * convention (an undefined ratio can't meet the bar either) -- this
   * component trusts the caller's own boolean rather than re-deriving it
   * from `ratio` itself, so it stays usable for any "value vs. a minimum"
   * reward:risk case, not just this one field.
   */
  meetsMinimum: boolean
  /** Decimal places for the ratio itself. Defaults to 1. */
  decimals?: number
}

/**
 * Colored reward:risk ratio display ("2.4:1"), styled by whether it clears
 * the caller's own minimum bar -- the inverse polarity of
 * `common/RiskPercent` (there, a *high* value is the breach; here, a *low*
 * value is). A failing ratio gets both a color change (the same
 * `riskBreach.main` warning red `RiskPercent`/`RiskPanel`'s row-highlight
 * already use for "this breaks one of the app's own hard rules") and a
 * `WarningAmberIcon`, since the task calling for this component explicitly
 * asks for a visual treatment distinct from "a plain number that looks the
 * same as a passing one" -- color alone can be too subtle/inaccessible on
 * its own. A passing ratio renders in `success.main` with no icon, and a
 * `null` ratio (no meaningful number to show at all) renders "n/a" in a
 * neutral, muted color -- never colored as if it failed the rule, since an
 * undefined ratio and a defined-but-failing one are different situations
 * worth reading differently.
 */
export default function RewardRiskBadge({
  ratio,
  meetsMinimum,
  decimals = 1,
}: RewardRiskBadgeProps) {
  const theme = useTheme()

  if (ratio === null) {
    return (
      <Typography component="span" style={{ color: theme.palette.text.secondary }}>
        n/a
      </Typography>
    )
  }

  const color = meetsMinimum ? theme.palette.success.main : theme.palette.riskBreach.main
  const label = `${ratio.toFixed(decimals)}:1`

  return (
    <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center', display: 'inline-flex' }}>
      {!meetsMinimum && (
        <WarningAmberIcon
          fontSize="small"
          style={{ color: theme.palette.riskBreach.main }}
          aria-label="Below the 2:1 minimum"
        />
      )}
      <Typography component="span" style={{ color, fontWeight: meetsMinimum ? 400 : 700 }}>
        {label}
      </Typography>
    </Stack>
  )
}
