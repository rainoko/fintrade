import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../tests/mocks/server'
import { ApiError } from './client'
import { getCftcCot } from './cftc'

describe('api/cftc', () => {
  it('getCftcCot returns all 5 fixed markets with their commercial/large-speculator/small-speculator positions', async () => {
    const response = await getCftcCot()

    expect(response.markets).toHaveLength(5)
    const keys = response.markets.map((market) => market.market_key)
    expect(keys).toEqual(['eur', 'jpy', 'oil', 'gold', 'bonds'])

    const eur = response.markets.find((market) => market.market_key === 'eur')
    expect(eur?.commercial_net).toBe(30000)
    expect(eur?.commercial_cot_index_52w).toBe(72.5)
  })

  it('returns a null COT Index for a market with fewer than 2 weeks of history (the fixed fixture\'s bonds entry)', async () => {
    const response = await getCftcCot()

    const bonds = response.markets.find((market) => market.market_key === 'bonds')
    expect(bonds?.weeks_of_history).toBe(1)
    expect(bonds?.commercial_cot_index_52w).toBeNull()
    expect(bonds?.large_speculator_cot_index_52w).toBeNull()
    expect(bonds?.small_speculator_cot_index_52w).toBeNull()
  })

  it('rejects with a 503 ApiError when the gateway/cache-miss live fetch fails', async () => {
    server.use(
      http.get('/api/cftc/cot', () =>
        HttpResponse.json(
          { detail: "The CFTC's data endpoint is currently unavailable." },
          { status: 503 },
        ),
      ),
    )

    await expect(getCftcCot()).rejects.toMatchObject({
      status: 503,
      detail: "The CFTC's data endpoint is currently unavailable.",
    } satisfies Partial<ApiError>)
  })
})
