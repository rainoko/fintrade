import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { resetPortfolioStore } from '../../tests/mocks/handlers'
import { server } from '../../tests/mocks/server'
import {
  getIbkrPortfolioPreview,
  getIbkrScannerParams,
  getIbkrStatus,
  preloadIbkrPortfolio,
  runIbkrScanner,
} from './ibkr'

describe('api/ibkr', () => {
  // preloadIbkrPortfolio's own test below mutates the shared in-memory
  // `positions` store (it actually imports NVDA) -- reset it so a later test
  // added to this file can't silently inherit that mutation.
  afterEach(() => {
    resetPortfolioStore()
  })

  it('getIbkrStatus returns the default disabled state, matching the real backend default', async () => {
    const status = await getIbkrStatus()

    expect(status.state).toBe('disabled')
    expect(status.detail).not.toBeNull()
  })

  it('getIbkrStatus surfaces the available state, with a null detail', async () => {
    server.use(
      http.get('/api/ibkr/status', () =>
        HttpResponse.json({ state: 'available', detail: null }),
      ),
    )

    const status = await getIbkrStatus()

    expect(status).toEqual({ state: 'available', detail: null })
  })

  it('getIbkrStatus rejects with an ApiError on a transport-level failure', async () => {
    server.use(http.get('/api/ibkr/status', () => HttpResponse.error()))

    await expect(getIbkrStatus()).rejects.toMatchObject({ status: 0 })
  })

  it('getIbkrScannerParams returns the available categories fixture', async () => {
    const response = await getIbkrScannerParams()

    expect(response.state).toBe('available')
    expect(response.categories).toEqual([
      { code: 'TOP_PERC_GAIN', display_name: 'Top % Gainers' },
      { code: 'TOP_PERC_LOSE', display_name: 'Top % Losers' },
      { code: 'HOT_BY_VOLUME', display_name: 'Hot by Volume' },
    ])
  })

  it('getIbkrScannerParams surfaces a disabled state as a normal (never rejecting) response', async () => {
    server.use(
      http.get('/api/ibkr/scanner/params', () =>
        HttpResponse.json({
          state: 'disabled',
          detail: 'IBKR integration is disabled.',
          categories: null,
        }),
      ),
    )

    const response = await getIbkrScannerParams()

    expect(response.state).toBe('disabled')
    expect(response.categories).toBeNull()
  })

  it('runIbkrScanner returns the completed scan results fixture', async () => {
    const response = await runIbkrScanner({
      scan_config: { instrument: 'STK', location: 'STK.US.MAJOR', type: 'TOP_PERC_GAIN' },
    })

    expect(response.state).toBe('available')
    expect(response.results).toHaveLength(2)
    expect(response.results?.[0]).toMatchObject({ symbol: 'AAPL', conid: 1001 })
  })

  it('runIbkrScanner rejects with a typed ApiError, exposing retryAfterSeconds, on a 429', async () => {
    server.use(
      http.post('/api/ibkr/scanner/run', () =>
        HttpResponse.json(
          { detail: 'Scanner rate limit exceeded; retry in 1 second.' },
          { status: 429, headers: { 'Retry-After': '1' } },
        ),
      ),
    )

    await expect(
      runIbkrScanner({ scan_config: { instrument: 'STK', location: 'STK.US.MAJOR', type: 'X' } }),
    ).rejects.toMatchObject({ status: 429, retryAfterSeconds: 1 })
  })

  it('getIbkrPortfolioPreview returns the available positions fixture, flagging the AAPL conflict', async () => {
    const response = await getIbkrPortfolioPreview()

    expect(response.state).toBe('available')
    expect(response.positions).toEqual([
      {
        conid: 265598,
        ticker: 'AAPL',
        quantity: 50,
        avg_cost: 150.25,
        conflicts_with_existing_position: true,
      },
      {
        conid: 272093,
        ticker: 'NVDA',
        quantity: 10,
        avg_cost: 900.5,
        conflicts_with_existing_position: false,
      },
    ])
  })

  it('getIbkrPortfolioPreview surfaces a disabled state as a normal (never rejecting) response', async () => {
    server.use(
      http.get('/api/ibkr/portfolio-preview', () =>
        HttpResponse.json({
          state: 'disabled',
          detail: 'IBKR integration is disabled.',
          positions: null,
        }),
      ),
    )

    const response = await getIbkrPortfolioPreview()

    expect(response.state).toBe('disabled')
    expect(response.positions).toBeNull()
  })

  it('getIbkrPortfolioPreview rejects with an ApiError on a 503', async () => {
    server.use(
      http.get('/api/ibkr/portfolio-preview', () =>
        HttpResponse.json({ detail: 'Account-positions fetch failed.' }, { status: 503 }),
      ),
    )

    await expect(getIbkrPortfolioPreview()).rejects.toMatchObject({ status: 503 })
  })

  it('preloadIbkrPortfolio imports the non-conflicting NVDA position, skipping conflicting AAPL', async () => {
    const response = await preloadIbkrPortfolio()

    expect(response.state).toBe('available')
    expect(response.imported).toEqual([
      expect.objectContaining({ ticker: 'NVDA', quantity: 10, avg_cost_basis: 900.5 }),
    ])
    expect(response.skipped_conflicting_tickers).toEqual(['AAPL'])
  })

  it('preloadIbkrPortfolio rejects with an ApiError on a 503', async () => {
    server.use(
      http.post('/api/ibkr/portfolio-preload', () =>
        HttpResponse.json({ detail: 'Account-positions fetch failed.' }, { status: 503 }),
      ),
    )

    await expect(preloadIbkrPortfolio()).rejects.toMatchObject({ status: 503 })
  })
})
