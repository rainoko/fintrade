import Alert, { type AlertColor } from '@mui/material/Alert'
import Typography from '@mui/material/Typography'
import type { HomeworkBand } from '../../../api/homework'

export interface HomeworkScoreBannerProps {
  totalScore: number
  band: HomeworkBand
}

const SEVERITY_BY_BAND: Record<HomeworkBand, AlertColor> = {
  red: 'error',
  yellow: 'warning',
  green: 'success',
}

// `band` alone doesn't distinguish the book's two very different "yellow"
// readings -- 5-6 ("trade cautiously") vs. 9-10 ("everything is so perfect,
// any change is bound to be for the worse") -- so this reads `totalScore`
// too, matching docs/ideas.md's ch. 57 entry / API.md's own band-threshold
// wording exactly rather than collapsing both into one generic caption.
function messageFor(totalScore: number, band: HomeworkBand): string {
  if (band === 'red') {
    return "Don't trade today."
  }
  if (band === 'green') {
    return 'Good to trade.'
  }
  if (totalScore >= 9) {
    return (
      'With everything so perfect, any change is bound to be for the worse -- stay disciplined ' +
      'and don\'t let a great score talk you into taking on more risk than usual.'
    )
  }
  return 'Trade cautiously.'
}

/**
 * Color-coded (red/yellow/green) summary banner for a daily homework
 * self-test score (Elder ch. 57, docs/Analyse.md/docs/ideas.md). Feature
 * component, not `components/common/`: `HomeworkBand` and its interpretive
 * copy ("trade cautiously", the "too perfect" caveat) are specific to this
 * self-test's own meaning of red/yellow/green, unlike `common/SignalBadge`
 * which is a pure color-by-string-union chip with no interpretive text of
 * its own -- see this task's `decisions` entry.
 */
export default function HomeworkScoreBanner({ totalScore, band }: HomeworkScoreBannerProps) {
  return (
    <Alert severity={SEVERITY_BY_BAND[band]} data-testid="homework-score-banner">
      <Typography sx={{ fontWeight: 700 }}>
        {totalScore}/10 -- {band.toUpperCase()}
      </Typography>
      <Typography variant="body2">{messageFor(totalScore, band)}</Typography>
    </Alert>
  )
}
