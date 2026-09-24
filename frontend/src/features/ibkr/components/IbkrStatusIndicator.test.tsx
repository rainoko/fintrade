import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { IBKRStatusResponse } from '../../../api/ibkr'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import IbkrStatusIndicator from './IbkrStatusIndicator'

function mockIbkrStatus(response: IBKRStatusResponse) {
  server.use(http.get('/api/ibkr/status', () => HttpResponse.json(response)))
}

describe('IbkrStatusIndicator', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows a loading spinner, then the disabled badge (the default MSW handler)', async () => {
    renderWithProviders(<IbkrStatusIndicator />)

    expect(screen.getByLabelText('Loading IBKR status')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('IBKR: Disabled')).toBeInTheDocument())
  })

  it('wraps its rendered chip in a role="status" live region, for a screen-reader user away from the app bar to be told about a silent background-poll state change', async () => {
    renderWithProviders(<IbkrStatusIndicator />)

    await waitFor(() => expect(screen.getByText('IBKR: Disabled')).toBeInTheDocument())
    expect(screen.getByRole('status')).toContainElement(screen.getByText('IBKR: Disabled'))
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

  it("flips to the 'Unknown' chip on a *later* background poll failure, rather than keeping the last successful state forever (regression: TanStack Query keeps the last-successful `data` populated across a failed background refetch)", async () => {
    mockIbkrStatus({ state: 'available', detail: null })
    vi.useFakeTimers()

    renderWithProviders(<IbkrStatusIndicator />)
    await vi.waitFor(() => expect(screen.getByText('IBKR: Connected')).toBeInTheDocument())

    // Flip the handler to a transport failure *after* the first successful
    // fetch, then advance past the hook's 30s `refetchInterval` so the next
    // background poll actually fires and fails.
    server.use(http.get('/api/ibkr/status', () => HttpResponse.error()))
    await vi.advanceTimersByTimeAsync(31_000)

    await vi.waitFor(() =>
      expect(screen.getByTestId('ibkr-status-indicator-unknown')).toBeInTheDocument(),
    )
    expect(screen.queryByText('IBKR: Connected')).not.toBeInTheDocument()
  })
})
