/**
 * Shared wording for `evaluate_tide`'s NEUTRAL-with-`weekly_macd_histogram_
 * slope === 'flat'` ambiguity (backend/app/signals/triple_screen.py):
 * `'flat'` covers two distinct causes -- a genuinely flat weekly
 * MACD-Histogram slope, or (via the <2-weekly-bar short-circuit) no slope
 * ever having been computed at all -- that `TideScreen`
 * (backend/app/api/schemas.py) doesn't expose separately, so this frontend
 * can't tell them apart from `trend`/`weekly_macd_histogram_slope` alone.
 * Naming both possibilities, rather than asserting either, is the most this
 * frontend can honestly say (see the frontend-stock-detail-metric-help-
 * followups task's `decisions` entry for how that was confirmed).
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
  'there isn’t enough weekly price history yet to compute a weekly MACD-Histogram slope, or the weekly slope is genuinely flat'
