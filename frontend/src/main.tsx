import CssBaseline from '@mui/material/CssBaseline'
import { ThemeProvider } from '@mui/material/styles'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.tsx'
import './index.css'
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
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
)
