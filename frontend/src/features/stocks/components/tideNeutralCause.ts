/**
 * Shared wording for `evaluate_tide`'s NEUTRAL-with-`weekly_macd_histogram_
 * slope === 'flat'` ambiguity (backend/app/signals/triple_screen.py). Screen
 * 1 (Tide) is the weekly Impulse System color as of `backend-weekly-impulse-
 * screen1`: `weekly_macd_histogram_slope` no longer decides `trend` -- the
 * weekly Impulse System's own EMA(13)-direction-vs-MACD-Histogram-direction
 * check does -- so `'flat'` here just means the *informational* slope
 * reading is ambiguous between two distinct causes `TideScreen`
 * (backend/app/api/schemas.py) doesn't expose separately: (a) a genuinely
 * small weekly MACD-Histogram step, with a real weekly Impulse Blue behind
 * it (the underlying EMA(13)/MACD-Histogram bar-over-bar directions still
 * disagreeing), or (b) the <2-weekly-bar short-circuit, where no weekly
 * Impulse color was ever computed at all. This frontend can't tell those two
 * apart from `trend`/`weekly_macd_histogram_slope` alone (a non-'flat'
 * slope, by contrast, proves there was enough weekly history to compute a
 * real weekly Impulse color, since the short-circuit always reports 'flat').
 * Naming both possibilities, rather than asserting either, is the most this
 * frontend can honestly say (see the frontend-stock-detail-metric-help-
 * followups task's `decisions` entry for how that was confirmed, and the
 * backend-weekly-impulse-screen1 task's `decisions` entry for the
 * methodology correction this wording was updated to reflect).
 *
 * `metricHelpContent.ts`'s `tideHelp.interpretValue` and
 * `signalExplanation.ts`'s `explainSignal` both need to state this same
 * hedge for their own Neutral-tide message -- previously each hardcoded its
 * own near-identical copy, which let the wording drift out of sync once
 * already (PR #127 fixed metricHelpContent.ts's copy; signalExplanation.ts's
 * independent copy of the same inaccuracy went unnoticed until PR #128).
 * Centralized here so a future wording fix only needs one edit (see the
 * frontend-stock-detail-metric-help-followups-followups task's `decisions`
 * entry).
 */
export const TIDE_INSUFFICIENT_HISTORY_OR_FLAT_SLOPE_HEDGE =
  'there isn’t enough weekly price history yet to compute the weekly Impulse System color, or the weekly MACD-Histogram’s own step is too small to call clearly rising or falling'
