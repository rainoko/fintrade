import { ThemeProvider } from '@mui/material/styles'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, type RenderOptions, type RenderResult } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { theme } from '../src/theme/theme'

/**
 * A fresh QueryClient per test: `retry: false` on both queries and
 * mutations so a mocked error response settles immediately instead of
 * TanStack Query's default retry/backoff delaying the error state a test
 * asserts on (the real app's client in main.tsx keeps `retry: 1` — this is
 * a test-speed decision, not a behavior change).
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
}

export interface RenderWithProvidersOptions extends RenderOptions {
  queryClient?: QueryClient
}

/**
 * Renders with the app's real MUI theme (see renderWithTheme.tsx) and a
 * QueryClientProvider, for any component/page that uses a feature hook under
 * features/.../hooks (usePortfolio, useAddPosition, ...) — those call
 * useQuery/useMutation, which throw "No QueryClient set" without one.
 *
 * Uses RTL's `wrapper` option (rather than nesting providers directly around
 * `ui` and passing that to `render`) specifically so the returned
 * `rerender(...)` keeps re-applying the same providers around whatever
 * element a test passes it next — nesting providers manually would silently
 * strip them on any `rerender` call, since RTL replaces exactly what was
 * originally rendered.
 */
export function renderWithProviders(
  ui: ReactElement,
  options?: RenderWithProvidersOptions,
): RenderResult {
  const { queryClient = createTestQueryClient(), ...renderOptions } = options ?? {}

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <ThemeProvider theme={theme}>{children}</ThemeProvider>
      </QueryClientProvider>
    )
  }

  return render(ui, { wrapper: Wrapper, ...renderOptions })
}
