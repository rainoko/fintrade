import { beforeEach, describe, expect, it } from 'vitest'
import { resetWatchlistStore } from '../../tests/mocks/handlers'
import { addWatchlistItem, getWatchlist, removeWatchlistItem } from './watchlist'

describe('api/watchlist', () => {
  beforeEach(() => {
    resetWatchlistStore()
  })

  it('getWatchlist returns every watched ticker, annotated with signal/confidence', async () => {
    const watchlist = await getWatchlist()

    expect(watchlist.items).toHaveLength(2)
    const aapl = watchlist.items.find((item) => item.ticker === 'AAPL')
    expect(aapl?.signal).toBe('BUY')
    expect(aapl?.confidence).toBe(72)
    expect(aapl?.confidence_band).toBe('High')
  })

  it('addWatchlistItem creates a new entry for a ticker not already watched, with a null signal', async () => {
    const created = await addWatchlistItem({ ticker: 'TSLA' })

    expect(created.ticker).toBe('TSLA')
    expect(created.signal).toBeNull()
    expect(created.confidence).toBeNull()
    expect(created.confidence_band).toBeNull()

    const watchlist = await getWatchlist()
    expect(watchlist.items.map((item) => item.ticker)).toContain('TSLA')
  })

  it('addWatchlistItem normalizes a lowercase ticker to uppercase', async () => {
    const created = await addWatchlistItem({ ticker: 'tsla' })
    expect(created.ticker).toBe('TSLA')
  })

  it('getWatchlist annotates a ticker with no computable signal as null, not a failed request', async () => {
    await addWatchlistItem({ ticker: 'ZZZZ' })

    const watchlist = await getWatchlist()
    const zzzz = watchlist.items.find((item) => item.ticker === 'ZZZZ')

    expect(zzzz?.signal).toBeNull()
    expect(zzzz?.confidence).toBeNull()
    expect(zzzz?.confidence_band).toBeNull()
  })

  it('addWatchlistItem is an idempotent no-op for a ticker already watched, keeping the original added_at', async () => {
    // Seeded item: AAPL, added_at 2026-09-10T09:15:00Z.
    const existing = (await getWatchlist()).items.find((item) => item.ticker === 'AAPL')

    const readded = await addWatchlistItem({ ticker: 'AAPL' })

    expect(readded.added_at).toBe(existing?.added_at)

    const watchlist = await getWatchlist()
    expect(watchlist.items.filter((item) => item.ticker === 'AAPL')).toHaveLength(1)
  })

  it('removeWatchlistItem removes an existing ticker', async () => {
    await expect(removeWatchlistItem('AAPL')).resolves.toBeUndefined()

    const watchlist = await getWatchlist()
    expect(watchlist.items.map((item) => item.ticker)).not.toContain('AAPL')
  })

  it('removeWatchlistItem throws a 404 ApiError for a ticker not on the watchlist', async () => {
    await expect(removeWatchlistItem('ZZZZ')).rejects.toMatchObject({ status: 404 })
  })
})
