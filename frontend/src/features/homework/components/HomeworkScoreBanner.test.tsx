import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import HomeworkScoreBanner from './HomeworkScoreBanner'

// Boundary values match the book's own thresholds (<=4 red, 5-6 yellow,
// 7-8 green, 9-10 yellow again) and the backend's own boundary tests
// (backend-daily-homework-self-test: 4/5, 6/7, 8/9) -- exercising the exact
// same edges on the frontend rather than only interior values.
describe('HomeworkScoreBanner', () => {
  it('renders red ("don\'t trade") at the top of the red band (score 4)', () => {
    renderWithTheme(<HomeworkScoreBanner totalScore={4} band="red" />)

    expect(screen.getByTestId('homework-score-banner')).toHaveClass('MuiAlert-colorError')
    expect(screen.getByText("Don't trade today.")).toBeInTheDocument()
    expect(screen.getByText('4/10 -- RED')).toBeInTheDocument()
  })

  it('renders yellow ("trade cautiously") at the bottom of the low-yellow band (score 5)', () => {
    renderWithTheme(<HomeworkScoreBanner totalScore={5} band="yellow" />)

    expect(screen.getByTestId('homework-score-banner')).toHaveClass('MuiAlert-colorWarning')
    expect(screen.getByText('Trade cautiously.')).toBeInTheDocument()
  })

  it('renders yellow ("trade cautiously") at the top of the low-yellow band (score 6)', () => {
    renderWithTheme(<HomeworkScoreBanner totalScore={6} band="yellow" />)

    expect(screen.getByTestId('homework-score-banner')).toHaveClass('MuiAlert-colorWarning')
    expect(screen.getByText('Trade cautiously.')).toBeInTheDocument()
  })

  it('renders green at the bottom of the green band (score 7)', () => {
    renderWithTheme(<HomeworkScoreBanner totalScore={7} band="green" />)

    expect(screen.getByTestId('homework-score-banner')).toHaveClass('MuiAlert-colorSuccess')
    expect(screen.getByText('Good to trade.')).toBeInTheDocument()
  })

  it('renders green at the top of the green band (score 8)', () => {
    renderWithTheme(<HomeworkScoreBanner totalScore={8} band="green" />)

    expect(screen.getByTestId('homework-score-banner')).toHaveClass('MuiAlert-colorSuccess')
    expect(screen.getByText('Good to trade.')).toBeInTheDocument()
  })

  it('renders yellow again with the "too perfect" caution at the bottom of the high-yellow band (score 9)', () => {
    renderWithTheme(<HomeworkScoreBanner totalScore={9} band="yellow" />)

    expect(screen.getByTestId('homework-score-banner')).toHaveClass('MuiAlert-colorWarning')
    expect(
      screen.getByText(/any change is bound to be for the worse/i),
    ).toBeInTheDocument()
  })

  it('renders yellow again with the "too perfect" caution at the top of the high-yellow band (score 10)', () => {
    renderWithTheme(<HomeworkScoreBanner totalScore={10} band="yellow" />)

    expect(screen.getByTestId('homework-score-banner')).toHaveClass('MuiAlert-colorWarning')
    expect(
      screen.getByText(/any change is bound to be for the worse/i),
    ).toBeInTheDocument()
    expect(screen.getByText('10/10 -- YELLOW')).toBeInTheDocument()
  })
})
