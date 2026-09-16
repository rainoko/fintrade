import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../tests/mocks/server'
import { ApiError } from './client'
import { getStockAnalysis, getStockHistory } from './stocks'

describe('api/stocks', () => {
  describe('getStockAnalysis', () => {
    it('returns the Triple Screen evaluation for a known ticker', async () => {
      const analysis = await getStockAnalysis('AAPL')

      expect(analysis.ticker).toBe('AAPL')
      expect(analysis.signal).toBe('BUY')
      expect(analysis.confidence_band).toBe('High')
    })

    it('throws a 404 ApiError for an unknown ticker', async () => {
      await expect(getStockAnalysis('UNKNOWN')).rejects.toMatchObject({
        status: 404,
      } satisfies Partial<ApiError>)
    })

    it('throws a 503 ApiError when the market data provider is unavailable', async () => {
      await expect(getStockAnalysis('NOPROVIDER')).rejects.toMatchObject({ status: 503 })
    })

    it('throws a 422 ApiError when there is insufficient weekly history', async () => {
      await expect(getStockAnalysis('THINHISTORY')).rejects.toMatchObject({ status: 422 })
    })
  })

  describe('getStockHistory', () => {
    it('requests with no query params when none are given, using the backend defaults', async () => {
      let requestedUrl: URL | undefined
      server.use(
        http.get('/api/stocks/:ticker/history', ({ request }) => {
          requestedUrl = new URL(request.url)
          return HttpResponse.json({ ticker: 'AAPL', interval: 'daily', bars: [] })
        }),
      )

      await getStockHistory('AAPL')

      expect(requestedUrl?.search).toBe('')
    })

    it('encodes range and interval as query params when given', async () => {
      const history = await getStockHistory('AAPL', { range: '6m', interval: 'weekly' })

      expect(history.interval).toBe('weekly')
      expect(history.bars.length).toBeGreaterThan(0)
    })

    it('URL-encodes the ticker path segment', async () => {
      let requestedPath: string | undefined
      server.use(
        http.get('/api/stocks/:ticker/history', ({ request }) => {
          requestedPath = new URL(request.url).pathname
          return HttpResponse.json({ ticker: 'BRK.A', interval: 'daily', bars: [] })
        }),
      )

      await getStockHistory('BRK/A')

      expect(requestedPath).toBe('/api/stocks/BRK%2FA/history')
    })

    it('throws a 422 ApiError for an unrecognized range value', async () => {
      await expect(
        getStockHistory('AAPL', { range: 'not-a-range' }),
      ).rejects.toMatchObject({
        status: 422,
      })
    })

    it('throws a 404 ApiError for an unknown ticker', async () => {
      await expect(getStockHistory('UNKNOWN')).rejects.toMatchObject({ status: 404 })
    })

    it('throws a 503 ApiError when the market data provider is unavailable', async () => {
      await expect(getStockHistory('NOPROVIDER')).rejects.toMatchObject({ status: 503 })
    })

    it('throws a 422 ApiError for weekly interval with insufficient history', async () => {
      await expect(
        getStockHistory('THINHISTORY', { interval: 'weekly' }),
      ).rejects.toMatchObject({
        status: 422,
      })
    })

    it('does not error for daily interval even for the thin-history sentinel ticker', async () => {
      const history = await getStockHistory('THINHISTORY', { interval: 'daily' })

      expect(history.ticker).toBe('THINHISTORY')
    })
  })
})
