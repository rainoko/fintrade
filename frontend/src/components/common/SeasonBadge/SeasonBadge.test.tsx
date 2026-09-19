import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import { theme } from '../../../theme/theme'
import SeasonBadge from './SeasonBadge'

describe('SeasonBadge', () => {
  it('renders the Spring label outlined in the spring color', () => {
    renderWithTheme(<SeasonBadge season="Spring" />)

    expect(screen.getByText('Spring')).toBeInTheDocument()
    expect(screen.getByTestId('season-badge')).toHaveStyle({
      color: theme.palette.season.spring,
      borderColor: theme.palette.season.spring,
    })
  })

  it('renders the Summer label outlined in the summer color', () => {
    renderWithTheme(<SeasonBadge season="Summer" />)

    expect(screen.getByText('Summer')).toBeInTheDocument()
    expect(screen.getByTestId('season-badge')).toHaveStyle({
      color: theme.palette.season.summer,
      borderColor: theme.palette.season.summer,
    })
  })

  it('renders the Autumn label outlined in the autumn color', () => {
    renderWithTheme(<SeasonBadge season="Autumn" />)

    expect(screen.getByText('Autumn')).toBeInTheDocument()
    expect(screen.getByTestId('season-badge')).toHaveStyle({
      color: theme.palette.season.autumn,
      borderColor: theme.palette.season.autumn,
    })
  })

  it('renders the Winter label outlined in the winter color', () => {
    renderWithTheme(<SeasonBadge season="Winter" />)

    expect(screen.getByText('Winter')).toBeInTheDocument()
    expect(screen.getByTestId('season-badge')).toHaveStyle({
      color: theme.palette.season.winter,
      borderColor: theme.palette.season.winter,
    })
  })

  it('never uses a filled variant, so it can never be mistaken for a common/SignalBadge chip', () => {
    renderWithTheme(<SeasonBadge season="Spring" />)

    // MUI applies `MuiChip-outlined` (not `MuiChip-filled`) as a class on
    // the outlined variant -- asserting the class directly, rather than
    // just eyeballing the visual, so a future accidental `variant="filled"`
    // regresses this test rather than only design review.
    expect(screen.getByTestId('season-badge').className).toContain('MuiChip-outlined')
  })
})
