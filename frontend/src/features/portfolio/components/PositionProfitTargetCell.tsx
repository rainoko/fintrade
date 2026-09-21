import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import type { RiskPosition } from '../../../api/portfolio'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import RewardRiskBadge from '../../../components/common/RewardRiskBadge/RewardRiskBadge'
import { formatCurrency } from '../../../utils/format'
import { profitTargetHelp } from './metricHelpContent'

export interface PositionProfitTargetCellProps {
  /**
   * `RiskPosition.profit_target` (`GET /api/portfolio/risk`), passed straight
   * through by `RiskPanel` -- normalized to `null` there (the field is
   * optional/nullable on the wire; both mean "no target" here). Purely
   * presentational: no fetch of its own. See this module's own doc comment
   * for why not.
   */
  profitTarget: RiskPosition['profit_target'] | null
}

/**
 * `RiskPanel`'s Profit Target column: one row's own suggested target price +
 * reward:risk ratio, read directly off `RiskPosition.profit_target` (`GET
 * /api/portfolio/risk`) -- computed for every open position regardless of
 * that ticker's current live signal (unlike `AnalysisResponse.profit_target`
 * on `GET /api/stocks/{ticker}/analysis`, still BUY-only), see the
 * `backend-profit-target-open-position` task's `decisions` entry.
 *
 * This component previously fetched `GET /api/stocks/{ticker}/analysis`
 * itself (`usePositionProfitTarget`), gated on `signal === 'BUY'` -- that
 * meant a held position whose signal had drifted to HOLD/SELL rendered an
 * em dash even though this app now has a real target for it. Removed
 * entirely (rather than kept alongside the new field) once `GET
 * /api/portfolio/risk` started carrying `profit_target` itself: `RiskPanel`
 * already has that response in hand for every other column, so a second,
 * redundant per-row network round trip added no information a fresh signal
 * ever needed either -- see this task's `decisions` entry for the full
 * reasoning against keeping both.
 *
 * Shares `RewardRiskBadge`/`profitTargetHelp`'s exact rendering/wording
 * pattern with `features/stocks/components/ProfitTargetDisplay.tsx` (the
 * stock-detail placement) as far as the `common/` layer allows, so the same
 * profit target for the same ticker can never visually disagree between the
 * two pages -- see the `frontend-profit-target-display` task's `decisions`
 * entry for why the two feature-level wrapper components themselves are
 * still separate, not one shared component imported across features.
 */
export default function PositionProfitTargetCell({
  profitTarget,
}: PositionProfitTargetCellProps) {
  const resolvedTarget = profitTarget ?? null

  const help = (
    <MetricHelp
      metricLabel={profitTargetHelp.metricLabel}
      definition={profitTargetHelp.definition}
      elderContext={profitTargetHelp.elderContext}
      valueInterpretation={profitTargetHelp.interpretValue(resolvedTarget)}
    />
  )

  if (!resolvedTarget) {
    return (
      <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center', justifyContent: 'flex-end' }}>
        <Typography variant="body2" color="text.secondary">
          —
        </Typography>
        {help}
      </Stack>
    )
  }

  return (
    <Stack
      direction="row"
      spacing={1}
      sx={{ alignItems: 'center', justifyContent: 'flex-end', flexWrap: 'wrap' }}
    >
      <Typography variant="body2">{formatCurrency(resolvedTarget.price)}</Typography>
      <RewardRiskBadge
        ratio={resolvedTarget.reward_risk_ratio ?? null}
        meetsMinimum={resolvedTarget.meets_minimum_reward_risk}
      />
      {help}
    </Stack>
  )
}
