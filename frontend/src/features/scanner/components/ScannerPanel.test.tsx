import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { resetWatchlistStore } from '../../../../tests/mocks/handlers'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import ScannerPanel from './ScannerPanel'

const categories = [
  { code: 'TOP_PERC_GAIN', display_name: 'Top % Gainers' },
  { code: 'TOP_PERC_LOSE', display_name: 'Top % Losers' },
]

function renderPanel() {
  return renderWithProviders(
    <MemoryRouter>
      <ScannerPanel categories={categories} />
    </MemoryRouter>,
  )
}

async function runScan(user: ReturnType<typeof userEvent.setup>, categoryLabel: string) {
  await user.click(screen.getByRole('combobox', { name: 'Scan category' }))
  await user.click(screen.getByRole('option', { name: categoryLabel }))
  await user.click(screen.getByRole('button', { name: 'Run scan' }))
}

describe('ScannerPanel', () => {
  beforeEach(() => {
    resetWatchlistStore()
  })

  it('runs a scan and shows the resulting candidates table', async () => {
    const user = userEvent.setup()
    renderPanel()

    await runScan(user, 'Top % Gainers')

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Scanner results' })).toBeInTheDocument(),
    )
    expect(screen.getByRole('link', { name: 'AAPL' })).toBeInTheDocument()
  })

  it('shows the empty-results state (not the unavailable state) for a zero-match scan', async () => {
    server.use(
      http.post('/api/ibkr/scanner/run', () =>
        HttpResponse.json({ state: 'available', detail: null, results: [] }),
      ),
    )
    const user = userEvent.setup()
    renderPanel()

    await runScan(user, 'Top % Gainers')

    await waitFor(() =>
      expect(screen.getByText('No matches for this scan.')).toBeInTheDocument(),
    )
    expect(screen.queryByText('Scanner unavailable')).not.toBeInTheDocument()
  })

  it('shows the unavailable state (not an error) when a run reports IBKR unavailable', async () => {
    server.use(
      http.post('/api/ibkr/scanner/run', () =>
        HttpResponse.json({
          state: 'gateway_unreachable',
          detail: 'The IBKR gateway did not answer.',
          results: null,
        }),
      ),
    )
    const user = userEvent.setup()
    renderPanel()

    await runScan(user, 'Top % Gainers')

    await waitFor(() =>
      expect(screen.getByText('Scanner unavailable')).toBeInTheDocument(),
    )
    expect(screen.getByText('The IBKR gateway did not answer.')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('surfaces a 429 rate-limit error via common/ErrorState with the retry delay', async () => {
    server.use(
      http.post('/api/ibkr/scanner/run', () =>
        HttpResponse.json(
          { detail: 'Scanner run rate limit exceeded.' },
          { status: 429, headers: { 'Retry-After': '1' } },
        ),
      ),
    )
    const user = userEvent.setup()
    renderPanel()

    await runScan(user, 'Top % Gainers')

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Too many requests')).toBeInTheDocument()
    expect(screen.getByText('Try again in 1s.')).toBeInTheDocument()
  })
})
