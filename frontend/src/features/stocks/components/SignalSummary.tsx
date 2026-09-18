import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import type { AnalysisResponse, ConfidenceBreakdownItem, Screens } from '../../../api/stocks'
import ConfidenceGauge from '../../../components/common/ConfidenceGauge/ConfidenceGauge'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import InfoBalloon from '../../../components/common/InfoBalloon/InfoBalloon'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import SignalBadge from '../../../components/common/SignalBadge/SignalBadge'
import { humanizeSnakeCase } from '../../../utils/format'
import { confidenceHelp, getConfidenceComponentHelp, signalHelp } from './metricHelpContent'
import SignalExplanationContent from './SignalExplanationContent'

export interface SignalSummaryProps {
  signal: AnalysisResponse['signal']
  confidence: AnalysisResponse['confidence']
  confidenceBand: AnalysisResponse['confidence_band']
  confidenceBreakdown: ConfidenceBreakdownItem[]
  /**
   * `GET /api/stocks/{ticker}/analysis`'s `screens` object -- drives the
   * click-to-explain "why this signal" balloon (see `signalExplanation.ts`).
   */
  screens: Screens
}

// Human-readable label per known confidence_breakdown component name
// (docs/Analyse.md §6). A future component name not in this map still
// renders via humanizeSnakeCase's fallback (underscores-to-spaces,
// capitalized), same shared helper RiskPanel's EXIT_FLAG_LABELS and
// ScreensPanel use.
const COMPONENT_LABELS: Record<string, string> = {
  tide_alignment: 'Tide alignment (Screen 1)',
  impulse_gate: 'Impulse gate',
  oscillator_extremity: 'Oscillator extremity (Screen 2)',
  elder_ray_confirmation: 'Elder-Ray confirmation',
  volume_confirmation: 'Volume confirmation',
}

function formatPercent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`
}

/**
 * Signal + confidence summary for `GET /api/stocks/{ticker}/analysis`
 * (docs/Analyse.md §6): the BUY/SELL/HOLD signal (common/SignalBadge), the
 * 0-100 confidence score with its Low/Medium/High band (common/ConfidenceGauge,
 * passed the API's own `confidence_band` field directly rather than letting
 * ConfidenceGauge re-derive it client-side, so the two can't silently drift
 * if Analyse.md §6's banding rule is ever revised — see
 * docs/tasks/frontend-common-components-followups.json), and an auditable
 * per-component breakdown table (weight/score) behind that score. Feature
 * component (not `common/`) since confidence_breakdown's component names
 * are Analyse.md §6 domain concepts.
 *
 * The signal badge itself is clickable (wrapped in common/InfoBalloon),
 * opening a balloon that explains WHY this signal resulted for this ticker
 * right now — the causal per-condition breakdown from signalExplanation.ts's
 * explainSignal, not a generic definition of what BUY/HOLD/SELL means
 * (that's frontend-stock-detail-metric-help's job) — see
 * docs/tasks/frontend-signal-why-explanation.json.
 *
 * A separate `common/MetricHelp` question-mark icon sits next to the badge
 * and next to the confidence gauge (frontend-stock-detail-metric-help):
 * these are the generic "what does BUY/SELL/HOLD mean, what is confidence,
 * how do they relate to Elder's methodology" explanations
 * (`metricHelpContent.ts`'s `signalHelp`/`confidenceHelp`), deliberately
 * distinct from the badge's own click-to-explain "why this result"
 * balloon above — the two don't duplicate or conflict, since one is
 * generic/definitional and the other is causal/ticker-specific. Each
 * confidence_breakdown row also gets its own inline `MetricHelp` (next to
 * the component name, not a corner overlay -- a table cell has no useful
 * "corner") explaining what that weighted component measures and how its
 * score/weight combination contributed to the total.
 */
export default function SignalSummary({
  signal,
  confidence,
  confidenceBand,
  confidenceBreakdown,
  screens,
}: SignalSummaryProps) {
  const columns: DataTableColumn<ConfidenceBreakdownItem>[] = [
    {
      key: 'component',
      header: 'Component',
      render: (row) => {
        const help = getConfidenceComponentHelp(row.component)
        return (
          <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
            <span>{humanizeSnakeCase(row.component, COMPONENT_LABELS)}</span>
            {help && (
              <MetricHelp
                metricLabel={help.metricLabel}
                definition={help.definition}
                elderContext={help.elderContext}
                valueInterpretation={help.interpretValue(row.score, row.weight)}
              />
            )}
          </Stack>
        )
      },
    },
    {
      key: 'weight',
      header: 'Weight',
      align: 'right',
      render: (row) => formatPercent(row.weight),
    },
    {
      key: 'score',
      header: 'Score',
      align: 'right',
      render: (row) => formatPercent(row.score),
    },
  ]

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
        <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
          <InfoBalloon
            triggerAriaLabel={`Why ${signal}?`}
            title={`Why ${signal}?`}
            content={<SignalExplanationContent signal={signal} screens={screens} />}
          >
            <SignalBadge signal={signal} />
          </InfoBalloon>
          <MetricHelp
            metricLabel={signalHelp.metricLabel}
            definition={signalHelp.definition}
            elderContext={signalHelp.elderContext}
            valueInterpretation={signalHelp.interpretValue(signal)}
          />
        </Stack>
        <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
          <ConfidenceGauge confidence={confidence} band={confidenceBand} />
          <MetricHelp
            metricLabel={confidenceHelp.metricLabel}
            definition={confidenceHelp.definition}
            elderContext={confidenceHelp.elderContext}
            valueInterpretation={confidenceHelp.interpretValue(confidence, confidenceBand)}
          />
        </Stack>
      </Stack>

      <Typography variant="subtitle2" color="text.secondary">
        Confidence breakdown
      </Typography>
      <DataTable
        columns={columns}
        rows={confidenceBreakdown}
        getRowKey={(row) => row.component}
        emptyMessage="No confidence breakdown available."
        ariaLabel="Confidence breakdown"
      />
    </Stack>
  )
}
