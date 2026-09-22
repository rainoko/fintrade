import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockMatchMedia } from '../../../tests/mockMatchMedia'
import { renderWithProviders } from '../../../tests/renderWithProviders'
import AppShell from './AppShell'

// renderWithProviders (not a bare ThemeProvider wrap) — AppShell now renders
// IbkrStatusIndicator (frontend-ibkr-status-indicator), which calls
// useIbkrStatus/useQuery and throws "No QueryClient set" without one. The
// default GET /api/ibkr/status MSW handler (tests/mocks/handlers.ts) covers
// every test in this file; none of them assert on the indicator itself
// (see IbkrStatusIndicator.test.tsx for that).
function renderShell(initialPath = '/') {
  return renderWithProviders(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<div>Dashboard content</div>} />
          <Route path="/portfolio" element={<div>Portfolio content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('AppShell', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the nav links and the routed page content', () => {
    mockMatchMedia(false)
    renderShell('/')

    expect(screen.getByRole('link', { name: /dashboard/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /portfolio/i })).toBeInTheDocument()
    expect(screen.getByText('Dashboard content')).toBeInTheDocument()
  })

  it('exposes exactly one nav landmark, not a nested pair', () => {
    // Regression test for the nested <nav> ARIA violation: AppShell's own
    // layout Box used to also carry `component="nav"` around NavDrawer's
    // <List component="nav">, producing two landmarks. Exactly one should
    // exist regardless of drawer variant.
    mockMatchMedia(false)
    renderShell('/')

    expect(screen.getAllByRole('navigation')).toHaveLength(1)
  })

  it('shows a permanent drawer with no hamburger toggle at desktop width', () => {
    mockMatchMedia(false)
    renderShell('/')

    expect(
      screen.queryByRole('button', { name: /open navigation/i }),
    ).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /portfolio/i })).toBeInTheDocument()
  })

  it('collapses to a hamburger-triggered temporary drawer below the sm breakpoint', async () => {
    mockMatchMedia(true)
    const user = userEvent.setup()
    renderShell('/')

    const toggle = screen.getByRole('button', { name: /open navigation/i })
    expect(toggle).toBeInTheDocument()
    // Temporary drawer starts closed — its nav links aren't rendered until opened.
    expect(screen.queryByRole('link', { name: /portfolio/i })).not.toBeInTheDocument()

    await user.click(toggle)

    expect(screen.getByRole('link', { name: /portfolio/i })).toBeInTheDocument()
  })

  it('closes the temporary drawer after navigating to a page', async () => {
    mockMatchMedia(true)
    const user = userEvent.setup()
    renderShell('/')

    await user.click(screen.getByRole('button', { name: /open navigation/i }))
    await user.click(screen.getByRole('link', { name: /portfolio/i }))

    // The temporary drawer's exit transition takes a beat in a real browser
    // (and jsdom doesn't fire transitionend, so MUI falls back to its own
    // timeout) — wait for the unmount rather than asserting synchronously.
    await waitFor(() => {
      expect(screen.queryByRole('link', { name: /portfolio/i })).not.toBeInTheDocument()
    })
  })
})
