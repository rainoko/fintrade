import SelfImprovementIcon from '@mui/icons-material/SelfImprovement'
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
// any change is bound to be for the worse") -- so the component below
// computes this once per render (matching docs/ideas.md's ch. 57 entry /
// API.md's own band-threshold wording exactly) and passes the result to
// `messageFor`/`iconFor`/the inline JSX label suffix, rather than each of
// those three call sites re-deriving the same `band === 'yellow' &&
// totalScore >= 9` condition independently -- which risked one getting out
// of sync with the others on a future threshold/band-naming change -- see
// this task's `decisions` entry (frontend-daily-homework-page-followups-followups).
function isTooPerfectBand(totalScore: number, band: HomeworkBand): boolean {
  return band === 'yellow' && totalScore >= 9
}

function messageFor(band: HomeworkBand, isTooPerfect: boolean): string {
  if (band === 'red') {
    return "Don't trade today."
  }
  if (band === 'green') {
    return 'Good to trade.'
  }
  if (isTooPerfect) {
    return (
      'With everything so perfect, any change is bound to be for the worse -- stay disciplined ' +
      'and don\'t let a great score talk you into taking on more risk than usual.'
    )
  }
  return 'Trade cautiously.'
}

// The 9-10 "too perfect" band is a behaviorally different caution from the
// 5-6 "trade cautiously" one (the former warns against overconfidence, not
// against a middling score), but MUI's default `severity="warning"` icon
// (a triangle exclamation) is identical for both -- indistinguishable at a
// glance, with only the body copy underneath telling them apart. Swapping in
// a distinct icon (rather than a different `severity`/color, which would
// falsely imply this band is somehow less risky than the 5-6 one -- Elder
// treats an over-perfect score as its own caution, not a lesser one) for the
// high-yellow case gives a fast-glance visual cue without changing the
// amber/warning color semantics -- see this task's `decisions` entry.
function iconFor(isTooPerfect: boolean) {
  if (isTooPerfect) {
    return <SelfImprovementIcon fontSize="inherit" />
  }
  return undefined
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
  const isTooPerfect = isTooPerfectBand(totalScore, band)

  return (
    <Alert
      severity={SEVERITY_BY_BAND[band]}
      icon={iconFor(isTooPerfect)}
      data-testid="homework-score-banner"
    >
      <Typography sx={{ fontWeight: 700 }}>
        {totalScore}/10 -- {band.toUpperCase()}
        {isTooPerfect ? ' (too perfect)' : ''}
      </Typography>
      <Typography variant="body2">{messageFor(band, isTooPerfect)}</Typography>
    </Alert>
  )
}
