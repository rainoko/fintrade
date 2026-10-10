import { describe, expect, it } from 'vitest'
import type { CFTCCOTMarketOut, CFTCCOTResponse } from '../../../api/cftc'
import { cftcCotHelp } from './cftcCotHelp'

function market(overrides: Partial<CFTCCOTMarketOut>): CFTCCOTMarketOut {
  return {
    market_key: 'eur',
    display_name: 'EURO FX - CHICAGO MERCANTILE EXCHANGE',
    report_date: '2026-09-29',
    open_interest: 650000,
    commercial_long: 120000,
    commercial_short: 90000,
    commercial_net: 30000,
    large_speculator_long: 95000,
    large_speculator_short: 115000,
    large_speculator_net: -20000,
    small_speculator_long: 40000,
    small_speculator_short: 30000,
    small_speculator_net: 10000,
    weeks_of_history: 52,
    commercial_cot_index_52w: 72.5,
    large_speculator_cot_index_52w: 18.0,
    small_speculator_cot_index_52w: 55.0,
    ...overrides,
  }
}

describe('cftcCotHelp', () => {
  it('always returns the same metricLabel/definition/elderContext', () => {
    const data: CFTCCOTResponse = { markets: [market({})] }
    const help = cftcCotHelp(data)

    expect(help.metricLabel).toBe('Commitments of Traders (COT)')
    expect(help.definition).toContain('Commitments of Traders')
    expect(help.elderContext).toMatch(/follow commercials.*fade small speculators/i)
  })

  it('names the highest and lowest commercial COT Index markets when at least 2 are computable', () => {
    // Deliberately non-monotonic order (highest/lowest are neither first nor
    // last) so both the "new extreme found" and "keep current extreme"
    // branches of the highest/lowest `reduce` comparisons each run at least
    // once -- not just the first comparison's outcome repeated.
    const data: CFTCCOTResponse = {
      markets: [
        market({ market_key: 'gold', display_name: 'GOLD', commercial_cot_index_52w: 45.0 }),
        market({ market_key: 'eur', display_name: 'EUR', commercial_cot_index_52w: 72.5 }),
        market({ market_key: 'oil', display_name: 'OIL', commercial_cot_index_52w: 12.0 }),
        market({ market_key: 'jpy', display_name: 'JPY', commercial_cot_index_52w: 30.0 }),
      ],
    }
    const help = cftcCotHelp(data)

    expect(help.valueInterpretation).toContain('most bullish')
    expect(help.valueInterpretation).toContain('EUR')
    expect(help.valueInterpretation).toContain('least bullish')
    expect(help.valueInterpretation).toContain('OIL')
  })

  it('names the single market when exactly one has a computable commercial COT Index', () => {
    const data: CFTCCOTResponse = {
      markets: [
        market({ market_key: 'eur', display_name: 'EUR', commercial_cot_index_52w: 50.0 }),
        market({ market_key: 'bonds', display_name: 'BONDS', commercial_cot_index_52w: null }),
      ],
    }
    const help = cftcCotHelp(data)

    expect(help.valueInterpretation).toBe(
      "EUR's commercials sit at a commercial COT Index of 50 -- the only market with a computable reading right now.",
    )
  })

  it('returns a null valueInterpretation when no market has a computable commercial COT Index', () => {
    const data: CFTCCOTResponse = {
      markets: [
        market({ market_key: 'eur', commercial_cot_index_52w: null }),
        market({ market_key: 'bonds', commercial_cot_index_52w: null }),
      ],
    }
    const help = cftcCotHelp(data)

    expect(help.valueInterpretation).toBeNull()
  })

  it('returns a null valueInterpretation when the market list is empty', () => {
    const data: CFTCCOTResponse = { markets: [] }
    const help = cftcCotHelp(data)

    expect(help.valueInterpretation).toBeNull()
  })

  it('names every tied market (not just one) when exactly 2 markets share the same commercial COT Index', () => {
    // Regression test: both are legitimately at their own trailing 52-week
    // extreme at the same time -- an ordinary occurrence, not a contrived
    // float coincidence -- so `highest`/`lowest` resolve to the same object
    // by reference, but BOTH are computable and tied, not "the only" one.
    const data: CFTCCOTResponse = {
      markets: [
        market({ market_key: 'eur', display_name: 'EUR', commercial_cot_index_52w: 100.0 }),
        market({ market_key: 'jpy', display_name: 'JPY', commercial_cot_index_52w: 100.0 }),
        market({ market_key: 'bonds', display_name: 'BONDS', commercial_cot_index_52w: null }),
      ],
    }
    const help = cftcCotHelp(data)

    expect(help.valueInterpretation).toBe(
      'Commercials are tied at a commercial COT Index of 100 across every market with a computable reading right now (EUR, JPY).',
    )
    expect(help.valueInterpretation).not.toContain('only market')
  })

  it('names every tied market when all computable markets share the same commercial COT Index', () => {
    const data: CFTCCOTResponse = {
      markets: [
        market({ market_key: 'eur', display_name: 'EUR', commercial_cot_index_52w: 0.0 }),
        market({ market_key: 'jpy', display_name: 'JPY', commercial_cot_index_52w: 0.0 }),
        market({ market_key: 'oil', display_name: 'OIL', commercial_cot_index_52w: 0.0 }),
        market({ market_key: 'gold', display_name: 'GOLD', commercial_cot_index_52w: 0.0 }),
        market({ market_key: 'bonds', display_name: 'BONDS', commercial_cot_index_52w: 0.0 }),
      ],
    }
    const help = cftcCotHelp(data)

    expect(help.valueInterpretation).toBe(
      'Commercials are tied at a commercial COT Index of 0 across every market with a computable reading right now (EUR, JPY, OIL, GOLD, BONDS).',
    )
    expect(help.valueInterpretation).not.toContain('only market')
  })
})
