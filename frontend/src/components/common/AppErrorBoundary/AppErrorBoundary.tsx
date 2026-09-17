import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Typography from '@mui/material/Typography'
import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

interface AppErrorBoundaryProps {
  children: ReactNode
}

interface AppErrorBoundaryState {
  error: Error | null
}

// Generic React error boundary: fully domain-agnostic (no position/ticker/
// signal knowledge) and reusable anywhere a render-time crash shouldn't take
// down more than the subtree it happens in — currently instantiated once,
// wrapping the whole routed app (see main.tsx), but nothing about it is
// app-shell-specific; a future feature could wrap just its own subtree with
// another instance. See docs/tasks/frontend-app-shell-navigation-followups.json
// for why this lives under components/common/ rather than components/layout/.
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
      return (
        <Box
          sx={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 2,
            minHeight: '100vh',
            p: 4,
            textAlign: 'center',
          }}
        >
          <Typography variant="h4" component="h1">
            Something went wrong
          </Typography>
          <Typography color="text.secondary">
            An unexpected error occurred while rendering this page. Try again, or reload
            the app.
          </Typography>
          <Button variant="contained" onClick={this.handleReset}>
            Try again
          </Button>
        </Box>
      )
    }

    return this.props.children
  }
}
