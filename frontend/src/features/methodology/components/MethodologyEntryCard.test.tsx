import { render, screen } from '@testing-library/react'
import { ThemeProvider } from '@mui/material/styles'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { theme } from '../../../theme/theme'
import type { MethodologyEntry } from '../data/methodologyContent'
import MethodologyEntryCard from './MethodologyEntryCard'

const baseEntry: MethodologyEntry = {
  id: 'test-entry',
  name: 'Test Indicator',
  citation: 'Elder, ch. 1, pp. 1-2',
  summary: 'A test summary.',
  elderContext: 'Some Elder context.',
  appStatus: 'informational',
  appBehavior: 'Exposed but not wired into the signal.',
}

function renderCard(entry: MethodologyEntry) {
  return render(
    <MemoryRouter>
      <ThemeProvider theme={theme}>
        <MethodologyEntryCard entry={entry} />
      </ThemeProvider>
    </MemoryRouter>,
  )
}

describe('MethodologyEntryCard', () => {
  it('renders the name, citation, summary, elder context, status, and app behavior', () => {
    renderCard(baseEntry)

    expect(screen.getByRole('heading', { name: 'Test Indicator' })).toBeInTheDocument()
    expect(screen.getByText('Elder, ch. 1, pp. 1-2')).toBeInTheDocument()
    expect(screen.getByText('A test summary.')).toBeInTheDocument()
    expect(screen.getByText('Some Elder context.')).toBeInTheDocument()
    expect(screen.getByText(/Computed & exposed/)).toBeInTheDocument()
    expect(screen.getByText(/Exposed but not wired into the signal\./)).toBeInTheDocument()
  })

  it('renders a cross-link when crossLinksTo is present', () => {
    renderCard({ ...baseEntry, crossLinksTo: 'Stock Detail page → Some Panel' })

    expect(screen.getByText(/See it live:/)).toBeInTheDocument()
  })

  it('renders no cross-link section when crossLinksTo is absent', () => {
    renderCard(baseEntry)

    expect(screen.queryByText(/See it live/)).not.toBeInTheDocument()
  })

  it('links a Stock Detail page cross-link to the Watchlist page (no ticker context here)', () => {
    renderCard({ ...baseEntry, crossLinksTo: 'Stock Detail page → Some Panel' })

    const link = screen.getByRole('link', { name: 'Stock Detail page → Some Panel' })
    expect(link).toHaveAttribute('href', '/watchlist')
  })

  it('links a Portfolio page cross-link directly to the Portfolio page', () => {
    renderCard({ ...baseEntry, crossLinksTo: 'Portfolio page → Risk Panel' })

    const link = screen.getByRole('link', { name: 'Portfolio page → Risk Panel' })
    expect(link).toHaveAttribute('href', '/portfolio')
  })

  it('links a Watchlist page cross-link directly to the Watchlist page', () => {
    renderCard({ ...baseEntry, crossLinksTo: 'Watchlist page → Personal Breadth card' })

    const link = screen.getByRole('link', { name: 'Watchlist page → Personal Breadth card' })
    expect(link).toHaveAttribute('href', '/watchlist')
  })

  it('renders plain, non-linked text for a crossLinksTo that names no known page', () => {
    renderCard({ ...baseEntry, crossLinksTo: 'Some other page → Some Panel' })

    expect(screen.getByText(/See it live: Some other page/)).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it.each([
    ['core_signal', /Active — feeds the signal/],
    ['risk_management', /Active — feeds portfolio risk/],
    ['considered', /Considered — not yet implemented/],
  ] as const)('renders the correct status chip for %s', (status, matcher) => {
    renderCard({ ...baseEntry, appStatus: status })

    expect(screen.getByText(matcher)).toBeInTheDocument()
  })
})
