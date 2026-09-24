import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { server } from '../../tests/mocks/server'
import { renderWithProviders } from '../../tests/renderWithProviders'
import ScannerPage from './ScannerPage'

function renderScannerPage() {
  return renderWithProviders(
    <MemoryRouter>
      <ScannerPage />
    </MemoryRouter>,
  )
}

describe('ScannerPage', () => {
  it('shows a loading state, then the category picker once params are available', async () => {
    renderScannerPage()

    expect(screen.getByText('Loading scan categories...')).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Scan category' })).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: 'Run scan' })).toBeInTheDocument()
  })

  it('shows the disabled/unavailable state (not an error) when IBKR is disabled', async () => {
    server.use(
      http.get('/api/ibkr/scanner/params', () =>
        HttpResponse.json({
          state: 'disabled',
          detail: 'IBKR integration is disabled (FINTRADE_IBKR_ENABLED is not set).',
          categories: null,
        }),
      ),
    )

    renderScannerPage()

    await waitFor(() => expect(screen.getByText('Scanner unavailable')).toBeInTheDocument())
    expect(
      screen.getByText('IBKR integration is disabled (FINTRADE_IBKR_ENABLED is not set).'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows the unavailable state for a not_authenticated gateway', async () => {
    server.use(
      http.get('/api/ibkr/scanner/params', () =>
        HttpResponse.json({
          state: 'not_authenticated',
          detail: 'The gateway session is not authenticated.',
          categories: null,
        }),
      ),
    )

    renderScannerPage()

    await waitFor(() => expect(screen.getByText('Scanner unavailable')).toBeInTheDocument())
    expect(
      screen.getByText('The gateway session is not authenticated.'),
    ).toBeInTheDocument()
  })

  it('surfaces a genuine transient failure (503) via common/ErrorState, distinct from the unavailable state', async () => {
    server.use(
      http.get('/api/ibkr/scanner/params', () =>
        HttpResponse.json(
          { detail: 'The scanner-params call itself failed transiently.' },
          { status: 503 },
        ),
      ),
    )

    renderScannerPage()

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Service unavailable')).toBeInTheDocument()
    expect(screen.queryByText('Scanner unavailable')).not.toBeInTheDocument()
  })
})
