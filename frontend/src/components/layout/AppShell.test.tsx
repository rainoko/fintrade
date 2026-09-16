import { ThemeProvider } from '@mui/material/styles'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { theme } from '../../theme/theme'
import AppShell from './AppShell'

function mockMatchMedia(matches: boolean) {
  vi.spyOn(window, 'matchMedia').mockImplementation(
    (query: string) =>
      ({
        matches,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  )
}

function renderShell(initialPath = '/') {
  return render(
    <ThemeProvider theme={theme}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<div>Dashboard content</div>} />
            <Route path="/portfolio" element={<div>Portfolio content</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
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
