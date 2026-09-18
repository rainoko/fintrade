import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import type { AnalysisResponse, ConfidenceBreakdownItem, Screens } from '../../../api/stocks'
import ConfidenceGauge from '../../../components/common/ConfidenceGauge/ConfidenceGauge'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import InfoBalloon from '../../../components/common/InfoBalloon/InfoBalloon'
import SignalBadge from '../../../components/common/SignalBadge/SignalBadge'
import { humanizeSnakeCase } from '../../../utils/format'
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
      render: (row) => humanizeSnakeCase(row.component, COMPONENT_LABELS),
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
      <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
        <InfoBalloon
          triggerAriaLabel={`Why ${signal}?`}
          title={`Why ${signal}?`}
          content={<SignalExplanationContent signal={signal} screens={screens} />}
        >
          <SignalBadge signal={signal} />
        </InfoBalloon>
        <ConfidenceGauge confidence={confidence} band={confidenceBand} />
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
