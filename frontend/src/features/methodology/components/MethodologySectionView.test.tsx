import { ThemeProvider } from '@mui/material/styles'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { theme } from '../../../theme/theme'
import type { MethodologySection } from '../data/methodologyContent'
import MethodologySectionView from './MethodologySectionView'

function renderSection(section: MethodologySection) {
  return render(
    <ThemeProvider theme={theme}>
      <MethodologySectionView section={section} />
    </ThemeProvider>,
  )
}

describe('MethodologySectionView', () => {
  it('renders the section title and intro', () => {
    renderSection({ id: 'overview', title: 'Overview', intro: 'Intro text.', entries: [] })

    expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByText('Intro text.')).toBeInTheDocument()
  })

  it('renders a card for every entry', () => {
    renderSection({
      id: 'screen-1',
      title: 'Screen 1',
      intro: 'Intro.',
      entries: [
        {
          id: 'a',
          name: 'Indicator A',
          citation: 'ch. 1',
          summary: 'Summary A',
          elderContext: 'Context A',
          appStatus: 'core_signal',
          appBehavior: 'Behavior A',
        },
        {
          id: 'b',
          name: 'Indicator B',
          citation: 'ch. 2',
          summary: 'Summary B',
          elderContext: 'Context B',
          appStatus: 'considered',
          appBehavior: 'Behavior B',
        },
      ],
    })

    expect(screen.getAllByTestId('methodology-entry-card')).toHaveLength(2)
    expect(screen.getByRole('heading', { name: 'Indicator A' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Indicator B' })).toBeInTheDocument()
  })

  it('renders no entry cards for an entries-free (overview) section', () => {
    renderSection({ id: 'overview', title: 'Overview', intro: 'Intro.', entries: [] })

    expect(screen.queryAllByTestId('methodology-entry-card')).toHaveLength(0)
  })
})
