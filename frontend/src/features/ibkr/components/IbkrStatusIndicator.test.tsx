import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { IBKRStatusResponse } from '../../../api/ibkr'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import IbkrStatusIndicator from './IbkrStatusIndicator'

function mockIbkrStatus(response: IBKRStatusResponse) {
  server.use(http.get('/api/ibkr/status', () => HttpResponse.json(response)))
}

describe('IbkrStatusIndicator', () => {
  it('shows a loading spinner, then the disabled badge (the default MSW handler)', async () => {
    renderWithProviders(<IbkrStatusIndicator />)

    expect(screen.getByLabelText('Loading IBKR status')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('IBKR: Disabled')).toBeInTheDocument())
  })

  it('renders the available state', async () => {
    mockIbkrStatus({ state: 'available', detail: null })

    renderWithProviders(<IbkrStatusIndicator />)

    await waitFor(() => expect(screen.getByText('IBKR: Connected')).toBeInTheDocument())
  })

  it('renders the gateway_unreachable state with its detail', async () => {
    mockIbkrStatus({
      state: 'gateway_unreachable',
      detail: 'IBKR gateway request to /iserver/auth/status failed',
    })

    renderWithProviders(<IbkrStatusIndicator />)

    await waitFor(() => expect(screen.getByText('IBKR: Gateway down')).toBeInTheDocument())
  })

  it('renders the not_authenticated state with its detail', async () => {
    mockIbkrStatus({ state: 'not_authenticated', detail: 'please log in' })

    renderWithProviders(<IbkrStatusIndicator />)

    await waitFor(() => expect(screen.getByText('IBKR: Sign-in needed')).toBeInTheDocument())
  })

  it("renders a distinct 'Unknown' chip on a transport-level failure, never claiming to know the gateway is down", async () => {
    server.use(http.get('/api/ibkr/status', () => HttpResponse.error()))

    renderWithProviders(<IbkrStatusIndicator />)

    await waitFor(() =>
      expect(screen.getByTestId('ibkr-status-indicator-unknown')).toBeInTheDocument(),
    )
    expect(screen.getByText('IBKR: Unknown')).toBeInTheDocument()
    expect(screen.queryByText('IBKR: Gateway down')).not.toBeInTheDocument()
  })
})
