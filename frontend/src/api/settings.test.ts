import { beforeEach, describe, expect, it } from 'vitest'
import { resetTradingModeStore } from '../../tests/mocks/handlers'
import { getTradingMode, updateTradingMode } from './settings'
import { ApiError } from './client'

describe('api/settings', () => {
  beforeEach(() => {
    resetTradingModeStore()
  })

  it('getTradingMode defaults to swing mode with a null triple', async () => {
    const response = await getTradingMode()

    expect(response.mode).toBe('swing')
    expect(response.day_trader_timeframe_triple).toBeNull()
  })

  it('updateTradingMode switches to day_trader mode and persists the triple', async () => {
    const response = await updateTradingMode({
      mode: 'day_trader',
      day_trader_timeframe_triple: {
        long_term: '25m',
        intermediate: '5m',
        short_term: '2m',
      },
    })

    expect(response.mode).toBe('day_trader')
    expect(response.day_trader_timeframe_triple).toMatchObject({
      long_term: '25m',
      intermediate: '5m',
      short_term: '2m',
    })

    const fetched = await getTradingMode()
    expect(fetched.mode).toBe('day_trader')
    expect(fetched.day_trader_timeframe_triple?.long_term).toBe('25m')
  })

  it('switching back to swing preserves a previously-configured triple', async () => {
    await updateTradingMode({
      mode: 'day_trader',
      day_trader_timeframe_triple: { long_term: '25m', intermediate: '5m', short_term: '2m' },
    })

    const response = await updateTradingMode({ mode: 'swing' })

    expect(response.mode).toBe('swing')
    expect(response.day_trader_timeframe_triple).toMatchObject({
      long_term: '25m',
      intermediate: '5m',
      short_term: '2m',
    })
  })

  it('rejects day_trader mode with no triple supplied (422)', async () => {
    const error = await updateTradingMode({ mode: 'day_trader' }).catch(
      (caught: unknown) => caught,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(422)
  })

  it('rejects a triple whose legs are not in strictly-decreasing order (422)', async () => {
    const error = await updateTradingMode({
      mode: 'day_trader',
      day_trader_timeframe_triple: { long_term: '2m', intermediate: '5m', short_term: '25m' },
    }).catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(422)
  })

  it('reports factor_of_five_warnings for a triple outside the guideline band', async () => {
    const response = await updateTradingMode({
      mode: 'day_trader',
      day_trader_timeframe_triple: { long_term: '10m', intermediate: '9m', short_term: '1m' },
    })

    expect(response.day_trader_timeframe_triple?.factor_of_five_warnings?.length).toBeGreaterThan(
      0,
    )
  })
})
