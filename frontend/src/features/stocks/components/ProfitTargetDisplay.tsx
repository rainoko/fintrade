import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import type { AnalysisResponse, ProfitTargetOut } from '../../../api/stocks'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import RewardRiskBadge from '../../../components/common/RewardRiskBadge/RewardRiskBadge'
import { formatCurrency } from '../../../utils/format'
import { profitTargetHelp } from './metricHelpContent'

export interface ProfitTargetDisplayProps {
  /** `AnalysisResponse.profit_target` -- null whenever `signal` isn't a fresh BUY, or a BUY with no current target candidate (see `profitTargetHelp`'s own null-cause branches). */
  profitTarget: ProfitTargetOut | null
  signal: AnalysisResponse['signal']
}

/**
 * Suggested profit target + reward:risk ratio for the current signal
 * (docs/Analyse.md §7, `backend-profit-target`) -- rendered inline next to
 * the signal/confidence badges in `SignalSummary` rather than as a
 * disconnected new section, per this task's own checklist. A failing
 * reward:risk ratio gets `common/RewardRiskBadge`'s visual warning
 * treatment (color + icon), not just a plain number -- Elder treats a sub-
 * 2:1 ratio as close to a hard no-trade rule ("it seldom pays to risk a
 * dollar to make a dollar"). The `—` null case (not a fresh BUY, or a BUY
 * with no current candidate) still gets a `MetricHelp` explaining *why*,
 * per this app's established explanatory pattern, rather than silently
 * omitting the row.
 */
export default function ProfitTargetDisplay({ profitTarget, signal }: ProfitTargetDisplayProps) {
  const help = (
    <MetricHelp
      metricLabel={profitTargetHelp.metricLabel}
      definition={profitTargetHelp.definition}
      elderContext={profitTargetHelp.elderContext}
      valueInterpretation={profitTargetHelp.interpretValue(profitTarget, signal)}
    />
  )

  if (!profitTarget) {
    return (
      <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
        <Typography variant="body2" color="text.secondary">
          Profit Target: —
        </Typography>
        {help}
      </Stack>
    )
  }

  return (
    <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
      <Typography variant="body2">Target {formatCurrency(profitTarget.price)}</Typography>
      <RewardRiskBadge
        ratio={profitTarget.reward_risk_ratio ?? null}
        meetsMinimum={profitTarget.meets_minimum_reward_risk}
      />
      {help}
    </Stack>
  )
}
