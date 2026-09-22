import { useState } from 'react'

/**
 * Resets a dialog's local form/mutation state whenever the subject it's
 * scoped to changes — including a transition to/from `null` (the dialog
 * closing) — so a second open doesn't start pre-filled with the previous
 * subject's answers or a stale result/error. `subjectId` is a plain
 * `string | null` identity (a ticker, a trade id, ...) rather than the full
 * subject object, so a caller only re-triggers the reset when the thing
 * being edited actually changes, not on every unrelated re-render.
 *
 * Done during render (React's own documented "adjusting state when a prop
 * changes" pattern: https://react.dev/learn/you-might-not-need-an-effect)
 * rather than inside a `useEffect`, so the reset lands in the same render as
 * the subject change instead of flashing the previous subject's stale state
 * for one frame first. `onReset` is called at most once per subject change
 * (the internal `prevSubjectId` comparison guards it — this hook never
 * causes a render loop), and doesn't need to be a stable/memoized reference:
 * a fresh inline closure per render is fine since it's only ever invoked
 * synchronously inside this same render pass, never stored or deferred.
 *
 * Extracted from `TradeApgarDialog`/`FollowUpReviewDialog`'s identical
 * `prevTicker`/`prevTradeId` boilerplate (frontend-trade-apgar-followups) so
 * a future fix to this pattern only needs to land in one place.
 */
export function useResetOnSubjectChange(subjectId: string | null, onReset: () => void): void {
  const [prevSubjectId, setPrevSubjectId] = useState<string | null>(subjectId)
  if (subjectId !== prevSubjectId) {
    setPrevSubjectId(subjectId)
    onReset()
  }
}
