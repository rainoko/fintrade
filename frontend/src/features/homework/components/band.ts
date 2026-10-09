import type { AlertColor } from '@mui/material/Alert'
import type { HomeworkBand } from '../../../api/homework'

// Plain `.ts` module (no component), mirroring `metricHelpContent.ts`'s own
// placement under `features/<domain>/components/` for a domain-specific,
// non-component helper shared by more than one component in this folder --
// keeping these two exports in `HomeworkScoreBanner.tsx` itself (a `.tsx`
// component file) would otherwise trip the repo's zero-warning
// `react-refresh/only-export-components` lint rule the moment a second
// component (`DailyHomeworkHistoryTable`) imports them, since that rule
// flags any `.tsx` file whose exports aren't *all* components.

/**
 * The book's own red/yellow/green color-banding convention for a daily
 * homework self-test score (Elder ch. 57) -- `HomeworkScoreBanner`'s
 * `Alert severity` and `DailyHomeworkHistoryTable`'s per-row `Chip color`
 * both reuse this exact mapping (this task's checklist item: "reuse
 * HomeworkScoreBanner's existing red/yellow/green band-coloring convention
 * rather than inventing a new color scheme" -- frontend-daily-homework-history)
 * rather than each independently re-deriving/hand-copying it.
 */
export const SEVERITY_BY_BAND: Record<HomeworkBand, AlertColor> = {
  red: 'error',
  yellow: 'warning',
  green: 'success',
}

/**
 * `band` alone doesn't distinguish the book's two very different "yellow"
 * readings -- 5-6 ("trade cautiously") vs. 9-10 ("everything is so perfect,
 * any change is bound to be for the worse") -- so both `HomeworkScoreBanner`
 * and `DailyHomeworkHistoryTable` compute this once (matching
 * docs/ideas.md's ch. 57 entry / API.md's own band-threshold wording
 * exactly) via this one shared predicate, rather than each re-deriving the
 * same `band === 'yellow' && totalScore >= 9` condition independently --
 * which risked drifting out of sync on a future threshold/band-naming
 * change -- see frontend-daily-homework-page-followups-followups' and this
 * task's (frontend-daily-homework-history) `decisions` entries.
 */
export function isTooPerfectBand(totalScore: number, band: HomeworkBand): boolean {
  return band === 'yellow' && totalScore >= 9
}
