import type { Theme } from '@mui/material/styles'

/**
 * Sign-to-color mapping shared by every signed-value display component
 * (`common/PercentChange`, `common/SignedCurrency`): positive -> theme
 * success color, negative -> theme error color, zero -> neutral secondary
 * text color. Extracted per frontend-trade-journal-followups (PR #150
 * review) so the app's gain/loss color convention lives in exactly one
 * place -- a future change to it (or a third signed-value component) only
 * needs to touch this function, not every ternary copy of it.
 */
export function signColor(theme: Theme, value: number): string {
  if (value > 0) {
    return theme.palette.success.main
  }
  if (value < 0) {
    return theme.palette.error.main
  }
  return theme.palette.text.secondary
}
