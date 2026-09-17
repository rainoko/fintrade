import CssBaseline from '@mui/material/CssBaseline'
import { ThemeProvider } from '@mui/material/styles'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.tsx'
import AppErrorBoundary from './components/layout/AppErrorBoundary.tsx'
import './index.css'
// Self-hosted Inter, the theme's primary font family (src/theme/theme.ts).
// Only the weights MUI's default Typography variants actually use (see
// createTheme's fontWeightLight/Regular/Medium/Bold defaults) — importing
// every weight would bloat the bundle for weights nothing renders.
import '@fontsource/inter/300.css'
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/700.css'
import { theme } from './theme/theme.ts'

// TanStack Query is the app's only server-state layer (see
// docs/architecture/Frontend.md §2) — every fetch/mutation hook under
// src/features/*/hooks goes through this client.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Market/portfolio data doesn't change second-to-second; avoid
      // refetching on every window focus and cap retries so a genuinely
      // down backend (503, per API.md) fails fast instead of hammering it.
      staleTime: 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: 0,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider theme={theme}>
          <CssBaseline />
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </AppErrorBoundary>
  </StrictMode>,
)
