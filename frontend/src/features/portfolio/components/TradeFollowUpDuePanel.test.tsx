import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { resetPortfolioStore } from '../../../../tests/mocks/handlers'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import TradeFollowUpDuePanel from './TradeFollowUpDuePanel'

function renderPanel() {
  return renderWithProviders(
    <MemoryRouter>
      <TradeFollowUpDuePanel />
    </MemoryRouter>,
  )
}

describe('TradeFollowUpDuePanel', () => {
  beforeEach(() => {
    resetPortfolioStore()
  })

  it('lists the trade the mock store seeds as due for follow-up review', async () => {
    renderPanel()

    expect(
      screen.getByText('Loading trades due for follow-up review...'),
    ).toBeInTheDocument()

    await waitFor(() =>
      expect(
        screen.getByRole('table', { name: 'Trades due for follow-up review' }),
      ).toBeInTheDocument(),
    )

    const row = screen.getByText('NVDA').closest('tr') as HTMLElement
    expect(within(row).getByRole('link', { name: 'NVDA' })).toHaveAttribute(
      'href',
      '/stocks/NVDA',
    )
    expect(within(row).getByText('+$200.00')).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'Record Review' })).toBeInTheDocument()
  })

  it('shows the empty state when nothing is currently due', async () => {
    server.use(
      http.get('/api/portfolio/closed-trades', () => HttpResponse.json({ items: [] })),
    )

    renderPanel()

    await waitFor(() =>
      expect(
        screen.getByText('No trades currently due for a follow-up review.'),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows a loading state, then an ApiError via common/ErrorState on failure', async () => {
    server.use(
      http.get('/api/portfolio/closed-trades', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )

    renderPanel()

    expect(
      screen.getByText('Loading trades due for follow-up review...'),
    ).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })

  // Timeout raised above vitest's 5000ms default, same rationale as
  // PortfolioPage.test.tsx's own raised-timeout test: real userEvent.type()
  // field entry plus two mounted-Dialog interactions is fast enough in
  // isolation, but v8 coverage instrumentation's per-file overhead during a
  // full coverage run intermittently pushes it past 5000ms.
  it(
    'records a follow-up review from the due list, which then drops the trade off the list',
    async () => {
      const user = userEvent.setup()
      renderPanel()

      await waitFor(() => expect(screen.getByText('NVDA')).toBeInTheDocument())

      await user.click(screen.getByRole('button', { name: 'Record Review' }))

      expect(screen.getByText('Follow-Up Review: NVDA')).toBeInTheDocument()
      await user.type(
        screen.getByLabelText('Follow-up notes'),
        'The tide was still bullish two months later -- sold too early.',
      )
      await user.click(screen.getByRole('button', { name: 'Save Review' }))

      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      await waitFor(() =>
        expect(
          screen.getByText('No trades currently due for a follow-up review.'),
        ).toBeInTheDocument(),
      )
    },
    15000,
  )
})
