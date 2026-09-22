import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../tests/mocks/server'
import { getIbkrScannerParams, runIbkrScanner } from './ibkr'

describe('api/ibkr', () => {
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
})
