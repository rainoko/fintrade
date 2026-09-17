import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Typography from '@mui/material/Typography'
import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

export interface AppErrorBoundaryProps {
  children: ReactNode
  /**
   * Whether the fallback should assume it's the only thing on the page:
   * sized to fill the viewport (`minHeight: 100vh`) with copy that mentions
   * reloading the whole app. Defaults to `true` (today's only usage, in
   * main.tsx, wrapping the entire routed app). Pass `false` when wrapping a
   * smaller feature subtree so the fallback sizes itself to that subtree
   * instead of the full viewport.
   */
  fullPage?: boolean
  /**
   * Overrides the fallback's body copy. Defaults to page-oriented wording
   * when `fullPage` is true, and to subtree-oriented wording (no mention of
   * "the app") when it's false.
   */
  message?: ReactNode
}

interface AppErrorBoundaryState {
  error: Error | null
}

// Generic React error boundary: fully domain-agnostic (no position/ticker/
// signal knowledge) and reusable anywhere a render-time crash shouldn't take
// down more than the subtree it happens in — currently instantiated once,
// wrapping the whole routed app (see main.tsx), but nothing about it is
// app-shell-specific; a future feature could wrap just its own subtree with
// another instance (pass `fullPage={false}` so the fallback sizes itself to
// that subtree rather than assuming it's the whole page). See
// docs/tasks/frontend-app-shell-navigation-followups.json for why this lives
// under components/common/ rather than components/layout/, and
// docs/tasks/frontend-app-shell-navigation-followups-followups.json for why
// the fallback's sizing/copy became props instead of being hardcoded for the
// whole-page case only.
//
// Deliberately separate from TanStack Query's per-query error state: a
// query's own `isError`/`error` only covers that one fetch failing, not
// e.g. a bug in how an already-successful response gets rendered — a
// render-time throw anywhere below this still needs to be caught
// somewhere, or the whole app unmounts to a blank page.
//
// React only supports error boundaries as class components (no hook
// equivalent exists), so this is the one class component in the app by
// necessity, not a style choice.
export default class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Only surfacing path for a render crash the UI has already caught and
    // replaced with a fallback.
    console.error('Unhandled render error caught by AppErrorBoundary', error, info)
  }

  handleReset = () => {
    this.setState({ error: null })
  }

  render() {
    if (this.state.error) {
      const { fullPage = true, message } = this.props
      const fallbackMessage =
        message ??
        (fullPage
          ? 'An unexpected error occurred while rendering this page. Try again, or reload the app.'
          : 'An unexpected error occurred while rendering this section. Try again.')

      return (
        <Box
          sx={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 2,
            // 100vh only makes sense when this boundary owns the whole page
            // (main.tsx's usage today); a subtree-scoped instance sizes
            // itself to its own content instead of forcing full-viewport
            // height onto whatever smaller area it actually wraps.
            minHeight: fullPage ? '100vh' : 200,
            p: fullPage ? 4 : 2,
            textAlign: 'center',
          }}
        >
          {/* Every page already renders its own `<h1>` via PageHeader
              (components/common/PageHeader/PageHeader.tsx). The default,
              fullPage usage (main.tsx, wrapping the whole routed app)
              replaces that page entirely, so `h1` is still correct there —
              but a fullPage={false} subtree usage renders alongside a
              page's own `<h1>`, so this must drop to `h2` to keep a single
              `h1` per document and a sane heading-navigation order for
              screen readers. */}
          <Typography variant="h4" component={fullPage ? 'h1' : 'h2'}>
            Something went wrong
          </Typography>
          <Typography color="text.secondary">{fallbackMessage}</Typography>
          <Button variant="contained" onClick={this.handleReset}>
            Try again
          </Button>
        </Box>
      )
    }

    return this.props.children
  }
}
