/**
 * Shared form-validation primitives. `isPositiveFinite` was previously
 * defined identically in both `AddPositionDialog.tsx` and
 * `ClosePositionDialog.tsx` (features/portfolio) -- extracted here per
 * frontend-close-position-dialog-followups (PR #261 round-2 review) so a
 * future change to the rule (e.g. allowing zero, or adding a max) only needs
 * to be made in one place instead of risking the two copies drifting out of
 * sync.
 */
export function isPositiveFinite(value: number): boolean {
  return Number.isFinite(value) && value > 0
}
