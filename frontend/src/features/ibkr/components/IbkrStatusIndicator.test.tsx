import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { IBKRStatusResponse } from '../../../api/ibkr'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import IbkrStatusIndicator from './IbkrStatusIndicator'

function mockIbkrStatus(response: IBKRStatusResponse) {
  server.use(http.get('/api/ibkr/status', () => HttpResponse.json(response)))
}

describe('IbkrStatusIndicator', () => {
  beforeEach(() => {
    vi.spyOn(window, 'open').mockImplementation(() => null)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
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

  it('shows a "Log in to IBKR" button when not_authenticated and login_url is present, and opens it in a new tab via window.open', async () => {
    const user = userEvent.setup()
    mockIbkrStatus({
      state: 'not_authenticated',
      detail: 'please log in',
      login_url: 'https://ibkr.home.arpa/',
    })

    renderWithProviders(<IbkrStatusIndicator />)

    const button = await screen.findByRole('button', { name: 'Log in to IBKR' })
    await user.click(button)

    expect(window.open).toHaveBeenCalledWith(
      'https://ibkr.home.arpa/',
      '_blank',
      'noopener,noreferrer',
    )
  })

  it('disables the login button right after a click, so rapid repeated clicks cannot open more than one duplicate login tab', async () => {
    mockIbkrStatus({
      state: 'not_authenticated',
      detail: 'please log in',
      login_url: 'https://ibkr.home.arpa/',
    })

    renderWithProviders(<IbkrStatusIndicator />)

    const button = await screen.findByRole('button', { name: 'Log in to IBKR' })
    // Native disabled buttons don't dispatch click events at all (matching real
    // browsers), so firing several clicks back-to-back in immediate succession --
    // rather than awaiting each one via userEvent -- is what actually exercises the
    // "rapid repeated clicks" scenario this guards against.
    fireEvent.click(button)
    expect(button).toBeDisabled()
    fireEvent.click(button)
    fireEvent.click(button)

    expect(window.open).toHaveBeenCalledTimes(1)
  })

  it('re-enables the login button again once its post-click cooldown elapses', async () => {
    mockIbkrStatus({
      state: 'not_authenticated',
      detail: 'please log in',
      login_url: 'https://ibkr.home.arpa/',
    })

    renderWithProviders(<IbkrStatusIndicator />)

    const button = await screen.findByRole('button', { name: 'Log in to IBKR' })
    fireEvent.click(button)
    expect(button).toBeDisabled()

    await waitFor(() => expect(button).toBeEnabled())
  })

  it('clears the login-return gate when the window never actually loses focus after the click (a likely popup-blocked window.open), so the next unrelated focus does not trigger a spurious extra status refetch', async () => {
    const user = userEvent.setup()
    vi.spyOn(document, 'hasFocus').mockReturnValue(true)
    let fetchCount = 0
    server.use(
      http.get('/api/ibkr/status', () => {
        fetchCount += 1
        return HttpResponse.json({
          state: 'not_authenticated',
          detail: 'please log in',
          login_url: 'https://ibkr.home.arpa/',
        } satisfies IBKRStatusResponse)
      }),
    )

    renderWithProviders(<IbkrStatusIndicator />)

    const button = await screen.findByRole('button', { name: 'Log in to IBKR' })
    await user.click(button)
    await waitFor(() => expect(fetchCount).toBeGreaterThan(0))
    const countBeforeUnrelatedFocus = fetchCount

    // Wait past the popup-blocked detection window before the unrelated focus event.
    await waitFor(() => expect(button).toBeEnabled())

    window.dispatchEvent(new Event('focus'))
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(fetchCount).toBe(countBeforeUnrelatedFocus)
  })

  it('keeps the login-return gate armed when the window did lose focus after the click (a likely successful window.open), still refetching once it regains focus later', async () => {
    const user = userEvent.setup()
    vi.spyOn(document, 'hasFocus').mockReturnValue(false)
    mockIbkrStatus({
      state: 'not_authenticated',
      detail: 'please log in',
      login_url: 'https://ibkr.home.arpa/',
    })

    renderWithProviders(<IbkrStatusIndicator />)

    const button = await screen.findByRole('button', { name: 'Log in to IBKR' })
    await user.click(button)

    // Wait past the popup-blocked detection window -- the gate should still be armed
    // since `document.hasFocus()` reports this window never regained focus.
    await waitFor(() => expect(button).toBeEnabled())

    mockIbkrStatus({ state: 'available', detail: null, login_url: 'https://ibkr.home.arpa/' })
    window.dispatchEvent(new Event('focus'))

    await waitFor(() => expect(screen.getByText('IBKR: Connected')).toBeInTheDocument())
  })

  it('does not render the login button for not_authenticated when login_url is unexpectedly absent', async () => {
    mockIbkrStatus({ state: 'not_authenticated', detail: 'please log in', login_url: null })

    renderWithProviders(<IbkrStatusIndicator />)

    await waitFor(() => expect(screen.getByText('IBKR: Sign-in needed')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Log in to IBKR' })).not.toBeInTheDocument()
  })

  it('does not render the login button for the available state even when login_url is present', async () => {
    mockIbkrStatus({ state: 'available', detail: null, login_url: 'https://ibkr.home.arpa/' })

    renderWithProviders(<IbkrStatusIndicator />)

    await waitFor(() => expect(screen.getByText('IBKR: Connected')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Log in to IBKR' })).not.toBeInTheDocument()
  })

  it('refetches the status immediately when the window regains focus after a login attempt was initiated', async () => {
    const user = userEvent.setup()
    mockIbkrStatus({
      state: 'not_authenticated',
      detail: 'please log in',
      login_url: 'https://ibkr.home.arpa/',
    })

    renderWithProviders(<IbkrStatusIndicator />)

    const button = await screen.findByRole('button', { name: 'Log in to IBKR' })
    await user.click(button)

    // Login "completed" server-side; the next refetch should pick it up.
    mockIbkrStatus({ state: 'available', detail: null, login_url: 'https://ibkr.home.arpa/' })

    window.dispatchEvent(new Event('focus'))

    await waitFor(() => expect(screen.getByText('IBKR: Connected')).toBeInTheDocument())
  })

  it('does not refetch on an unrelated window focus event before any login attempt was initiated', async () => {
    let fetchCount = 0
    server.use(
      http.get('/api/ibkr/status', () => {
        fetchCount += 1
        return HttpResponse.json({
          state: 'not_authenticated',
          detail: 'please log in',
          login_url: 'https://ibkr.home.arpa/',
        } satisfies IBKRStatusResponse)
      }),
    )

    renderWithProviders(<IbkrStatusIndicator />)

    await waitFor(() => expect(screen.getByText('IBKR: Sign-in needed')).toBeInTheDocument())
    const countAfterInitialFetch = fetchCount

    window.dispatchEvent(new Event('focus'))

    // Give any (undesired) refetch a chance to fire before asserting it didn't.
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(fetchCount).toBe(countAfterInitialFetch)
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
