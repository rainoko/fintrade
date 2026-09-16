import { ThemeProvider } from '@mui/material/styles'
import { render, type RenderOptions, type RenderResult } from '@testing-library/react'
import type { ReactElement } from 'react'
import { theme } from '../src/theme/theme'

/**
 * Renders with the app's real MUI theme (src/theme/theme.ts) so components
 * that read a custom palette entry (e.g. `theme.palette.signal.buy`) behave
 * as they do in the app, instead of falling back to MUI's bare default
 * theme (which has no `signal`/`riskBreach` palette and would throw).
 * Storybook wires the same theme globally via .storybook/preview.tsx; tests
 * need to opt in per-render since RTL has no global provider wrapper.
 */
export function renderWithTheme(ui: ReactElement, options?: RenderOptions): RenderResult {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>, options)
}
