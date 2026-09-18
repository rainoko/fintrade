import HelpOutlineIcon from '@mui/icons-material/HelpOutlineOutlined'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import InfoBalloon from '../InfoBalloon/InfoBalloon'

export interface MetricHelpProps {
  /** Short label naming the metric, e.g. "EMA (13)" -- becomes the popover title and the trigger's accessible name ("<metricLabel> help"). */
  metricLabel: string
  /** Plain-language definition of what this metric/signal is. */
  definition: string
  /** How this metric fits Dr. Elder's Triple Screen/Impulse/confidence-scoring methodology -- should cite the specific docs/Analyse.md section it's grounded in. */
  elderContext: string
  /**
   * Interpretation of the *current* value shown for this metric, when one
   * can be meaningfully computed (e.g. "36.9 is in the neutral zone
   * (30-70): neither overbought nor oversold"). Omit, or pass `null`, when
   * no current-value interpretation applies (e.g. this metric isn't backed
   * by a live value at this call site).
   */
  valueInterpretation?: string | null
}

/**
 * Small question-mark affordance that opens a three-part explanation of a
 * metric/signal shown elsewhere on the page: what it is, how it relates to
 * Elder's methodology, and (where available) what the specific current
 * value means. Built on `common/InfoBalloon` (frontend-signal-why-
 * explanation) rather than a second balloon/popover mechanism -- this
 * component only supplies the trigger icon and the three-part content
 * layout, reusing InfoBalloon's open/close/anchor behavior as-is.
 *
 * Deliberately domain-agnostic: it takes plain strings, not an
 * Elder-specific object -- the actual Triple Screen/confidence-scoring
 * content lives in `features/stocks/components/metricHelpContent.ts`'s
 * registry, keeping this component reusable for any metric on any page,
 * per Frontend.md §3's common/-vs-feature-specific placement test (see
 * the frontend-stock-detail-metric-help task's `decisions` entry).
 *
 * No default corner-positioning `sx` is applied here -- callers place the
 * trigger inline within their own layout (e.g. a card's title row, a table
 * cell) rather than this component prescribing an absolute-position
 * overlay; see this task's `decisions` entry for why (short-answer:
 * several call sites -- a Chip, a LinearProgress bar, a table cell -- are
 * too visually compact for an overlapping absolute-positioned icon to read
 * as "in the corner" rather than "on top of").
 */
export default function MetricHelp({
  metricLabel,
  definition,
  elderContext,
  valueInterpretation,
}: MetricHelpProps) {
  return (
    <InfoBalloon
      triggerAriaLabel={`${metricLabel} help`}
      title={metricLabel}
      content={
        <Stack spacing={1} sx={{ maxWidth: 360 }}>
          <Typography variant="body2">{definition}</Typography>
          <Typography variant="body2" color="text.secondary">
            {elderContext}
          </Typography>
          {valueInterpretation && (
            <Typography variant="body2" sx={{ fontWeight: 600 }}>
              {valueInterpretation}
            </Typography>
          )}
        </Stack>
      }
    >
      <HelpOutlineIcon fontSize="small" color="action" data-testid="metric-help-icon" />
    </InfoBalloon>
  )
}
