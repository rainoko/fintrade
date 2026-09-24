import { useState } from 'react'

/**
 * Runs `onChange` whenever `value` differs from the value this hook last
 * saw — including the very first change away from whatever `value` was at
 * mount — comparing (via `===`) and reacting during render (React's own
 * documented "adjusting state when a prop changes" pattern:
 * https://react.dev/learn/you-might-not-need-an-effect) rather than inside a
 * `useEffect`, so the reaction lands in the same render as the value change
 * instead of committing the previous value for one extra frame first.
 * `onChange` receives the new value, is called at most once per actual
 * change (the internal `prevValue` comparison guards it — this hook never
 * causes a render loop), and doesn't need to be a stable/memoized reference:
 * a fresh inline closure per render is fine since it's only ever invoked
 * synchronously inside this same render pass, never stored or deferred.
 *
 * Generalized from `useResetOnSubjectChange` below (this hook's original,
 * narrower motivating case — a dialog's subject identity changing, which
 * only needs to know *that* it changed, not the new value) so
 * `DailyHomeworkForm`'s suggestion-driven prefill
 * (frontend-daily-homework-page-followups-followups-followups) could reuse
 * the same compare-and-react-during-render shape instead of hand-rolling an
 * independent copy of it, since that use case needs the new value itself
 * inside the callback (to conditionally prefill `yesterday_trading_score`)
 * — see that component's own `HomeworkQuestionsForm` for the second use
 * site.
 */
export function useOnValueChange<T>(value: T, onChange: (value: T) => void): void {
  const [prevValue, setPrevValue] = useState<T>(value)
  if (value !== prevValue) {
    setPrevValue(value)
    onChange(value)
  }
}

/**
 * Resets a dialog's local form/mutation state whenever the subject it's
 * scoped to changes — including a transition to/from `null` (the dialog
 * closing) — so a second open doesn't start pre-filled with the previous
 * subject's answers or a stale result/error. `subjectId` is a plain
 * `string | null` identity (a ticker, a trade id, ...) rather than the full
 * subject object, so a caller only re-triggers the reset when the thing
 * being edited actually changes, not on every unrelated re-render. A thin
 * wrapper around `useOnValueChange` above, kept for its existing call
 * sites' `onReset: () => void` shape (they don't need the new value itself).
 *
 * Extracted from `TradeApgarDialog`/`FollowUpReviewDialog`'s identical
 * `prevTicker`/`prevTradeId` boilerplate (frontend-trade-apgar-followups) so
 * a future fix to this pattern only needs to land in one place.
 */
export function useResetOnSubjectChange(subjectId: string | null, onReset: () => void): void {
  useOnValueChange(subjectId, onReset)
}
