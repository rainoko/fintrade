import { render, screen } from '@testing-library/react'
import { ThemeProvider } from '@mui/material/styles'
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
    <ThemeProvider theme={theme}>
      <MethodologyEntryCard entry={entry} />
    </ThemeProvider>,
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

    expect(screen.getByText(/See it live: Stock Detail page/)).toBeInTheDocument()
  })

  it('renders no cross-link section when crossLinksTo is absent', () => {
    renderCard(baseEntry)

    expect(screen.queryByText(/See it live/)).not.toBeInTheDocument()
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
