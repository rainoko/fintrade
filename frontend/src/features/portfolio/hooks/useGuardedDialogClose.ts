/**
 * Wraps a dialog's `onClose` so MUI's `Dialog` can't dismiss it via
 * Escape/backdrop-click while `isPending` is true. MUI's `Dialog` fires its
 * own `onClose` on both of those paths regardless of any button's own
 * `disabled` state, so guarding only a dialog's explicit Cancel/Done button
 * isn't enough by itself — a mutation-in-flight dialog needs its `onClose`
 * itself guarded too, or a user can dismiss it mid-mutation. The mutation
 * itself keeps running in the background either way (only the visual dialog
 * closes), but the success/error outcome is then silently discarded once the
 * dialog is reopened and its local state resets.
 *
 * Extracted from `IbkrPreloadDialog`'s original inline `handleDialogClose`
 * (frontend-ibkr-portfolio-preload-followups #3) once `AddPositionDialog`'s
 * identical, pre-existing gap needed the exact same three-line guard
 * (frontend-ibkr-portfolio-preload-followups-followups) — a second real call
 * site, not a speculative one, so sharing it here means a future fix to this
 * pattern only needs to land in one place (same rationale
 * `useResetOnSubjectChange` already documents for its own extraction).
 */
export function useGuardedDialogClose(onClose: () => void, isPending: boolean): () => void {
  return () => {
    if (isPending) {
      return
    }
    onClose()
  }
}
