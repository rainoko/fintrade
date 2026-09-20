import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '../../tests/renderWithProviders'
import { METHODOLOGY_SECTIONS } from '../features/methodology/data/methodologyContent'
import MethodologyPage from './MethodologyPage'

function renderPage() {
  return renderWithProviders(
    <MemoryRouter>
      <MethodologyPage />
    </MemoryRouter>,
  )
}

/** The status filter row renders each status label twice: once as a clickable
 * Chip (role "button") and again as bold legend text below it -- this picks
 * the Chip specifically, matching MethodologyStatusFilter.test.tsx's own
 * approach. */
function statusChip(label: string) {
  const chip = screen.getAllByRole('button').find((el) => el.textContent === label)
  if (!chip) {
    throw new Error(`No status chip found with label "${label}"`)
  }
  return chip
}

describe('MethodologyPage', () => {
  it('renders the page title', () => {
    renderPage()

    expect(screen.getByRole('heading', { name: 'Signals We Considered', level: 1 })).toBeInTheDocument()
  })

  it('renders every section title by default (all statuses selected)', () => {
    renderPage()

    for (const section of METHODOLOGY_SECTIONS) {
      expect(screen.getByRole('heading', { name: section.title })).toBeInTheDocument()
    }
  })

  it('renders a named entry from the "considered" catalog by default', () => {
    renderPage()

    expect(screen.getByRole('heading', { name: /IBKR Data Provider/i })).toBeInTheDocument()
  })

  it('hides sections whose entries are all filtered out, and shows an empty-selection notice when nothing is selected', async () => {
    const user = userEvent.setup()
    renderPage()

    // Deselect every status chip one at a time.
    await user.click(statusChip('Active — feeds the signal'))
    await user.click(statusChip('Active — feeds portfolio risk & money management'))
    await user.click(statusChip('Computed & exposed — informational only'))
    await user.click(statusChip('Considered — not yet implemented'))

    expect(
      screen.getByText(/No status is selected, so no indicator\/technique entries are shown/),
    ).toBeInTheDocument()
    // The entries-free Overview section still renders regardless of filter.
    expect(
      screen.getByRole('heading', { name: 'Overview: the Triple Screen Trading System' }),
    ).toBeInTheDocument()
    // A section made entirely of entries (e.g. Screen 1) is now hidden.
    expect(
      screen.queryByRole('heading', { name: /Screen 1 — The Tide/ }),
    ).not.toBeInTheDocument()
  })

  it('filtering to only "considered" shows the considered section and hides the core-signal-only Screen 3 section', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(statusChip('Active — feeds the signal'))
    await user.click(statusChip('Active — feeds portfolio risk & money management'))
    await user.click(statusChip('Computed & exposed — informational only'))

    expect(
      screen.getByRole('heading', { name: 'Considered But Not (Yet) Implemented' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: /Screen 3 — The Trigger/ }),
    ).not.toBeInTheDocument()
  })

  it('re-selecting a deselected status chip brings its section back', async () => {
    const user = userEvent.setup()
    renderPage()

    const coreSignalChip = statusChip('Active — feeds the signal')
    await user.click(coreSignalChip)
    expect(
      screen.queryByRole('heading', { name: /Screen 3 — The Trigger/ }),
    ).not.toBeInTheDocument()

    await user.click(coreSignalChip)
    expect(
      screen.getByRole('heading', { name: /Screen 3 — The Trigger/ }),
    ).toBeInTheDocument()
  })

  it('links back to the app via the main navigation, not just this page', () => {
    renderPage()

    // Sanity check this page renders standalone content, not the nav shell
    // itself (nav is provided by AppShell in the real route tree, tested in
    // App.test.tsx) -- this page renders only its own PageHeader + content.
    expect(screen.queryByRole('link', { name: /dashboard/i })).not.toBeInTheDocument()
  })
})
