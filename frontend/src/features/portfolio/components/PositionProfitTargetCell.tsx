import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import type { PositionOut } from '../../../api/portfolio'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import RewardRiskBadge from '../../../components/common/RewardRiskBadge/RewardRiskBadge'
import { formatCurrency } from '../../../utils/format'
import { usePositionProfitTarget } from '../hooks/usePositionProfitTarget'
import { profitTargetHelp } from './metricHelpContent'

export interface PositionProfitTargetCellProps {
  ticker: string
  /**
   * This position's own current signal -- `RiskPanel`'s `signalByTicker`
   * cross-reference (same source `PositionsTable`'s own Signal column
   * reads, `PositionOut.signal`). Gates whether an analysis fetch is even
   * attempted (`usePositionProfitTarget`'s `enabled` param) and drives which
   * of `profitTargetHelp.interpretValue`'s three null-cause branches
   * applies when there's no target to show.
   */
  signal: PositionOut['signal']
}

/**
 * `RiskPanel`'s Profit Target column: one row's own suggested target price +
 * reward:risk ratio, fetched per-ticker from `GET /api/stocks/{ticker}/
 * analysis` (`usePositionProfitTarget`) since `GET /api/portfolio/risk`
 * itself doesn't carry `profit_target` (see that hook's own doc comment).
 * Only fires the fetch at all when `signal === 'BUY'` -- otherwise renders
 * the explained em-dash immediately, no network round trip needed, since
 * `profit_target` is contractually null for every other signal.
 *
 * Shares `RewardRiskBadge`/`profitTargetHelp`'s exact rendering/wording with
 * `features/stocks/components/ProfitTargetDisplay.tsx` (the stock-detail
 * placement) as far as the `common/` layer allows, so the same profit
 * target for the same ticker can never visually disagree between the two
 * pages -- see this task's `decisions` entry for why the two feature-level
 * wrapper components themselves are still separate, not one shared
 * component imported across features.
 */
export default function PositionProfitTargetCell({
  ticker,
  signal,
}: PositionProfitTargetCellProps) {
  // Normalizes `undefined` (an omitted-from-the-fixture PositionOut.signal,
  // never actually produced by the real backend) to `null`, matching
  // `RiskPanel`'s own `signalByTicker.get(...) ?? null` convention -- keeps
  // `profitTargetHelp.interpretValue`'s signature to the two states that
  // are actually meaningfully distinct (a definite signal, or "couldn't be
  // computed"), not three.
  const normalizedSignal = signal ?? null
  const isBuy = normalizedSignal === 'BUY'
  const query = usePositionProfitTarget(ticker, isBuy)

  if (isBuy && query.isLoading) {
    return (
      <Typography variant="body2" color="text.secondary">
        Checking…
      </Typography>
    )
  }

  // A fetch error is folded into the same "unavailable" null-cause branch
  // as "BUY but no candidate" (both render the same explained em dash) --
  // see this task's `decisions` entry for why a fetch-specific message
  // wasn't added as a fourth branch.
  const profitTarget = isBuy && !query.isError ? (query.data?.profit_target ?? null) : null

  const help = (
    <MetricHelp
      metricLabel={profitTargetHelp.metricLabel}
      definition={profitTargetHelp.definition}
      elderContext={profitTargetHelp.elderContext}
      valueInterpretation={profitTargetHelp.interpretValue(profitTarget, normalizedSignal)}
    />
  )

  if (!profitTarget) {
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
      <Typography variant="body2">{formatCurrency(profitTarget.price)}</Typography>
      <RewardRiskBadge
        ratio={profitTarget.reward_risk_ratio ?? null}
        meetsMinimum={profitTarget.meets_minimum_reward_risk}
      />
      {help}
    </Stack>
  )
}
