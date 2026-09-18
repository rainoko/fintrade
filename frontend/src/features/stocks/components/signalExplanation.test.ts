import { describe, expect, it } from 'vitest'
import type { Screens } from '../../../api/stocks'
import { explainSignal } from './signalExplanation'

function screens(overrides: Partial<{
  tideTrend: Screens['tide']['trend']
  impulse: Screens['impulse']
  waveState: string
  triggerFired: boolean
  triggerReference: string
}>): Screens {
  const {
    tideTrend = 'BULLISH',
    impulse = 'GREEN',
    waveState = 'OVERSOLD_PULLBACK',
    triggerFired = true,
    triggerReference = 'close_above_prior_high',
  } = overrides
  return {
    tide: { trend: tideTrend, weekly_macd_histogram_slope: 'rising' },
    impulse,
    wave: { stochastic_k: 24.3, force_index_2ema: -18234.5, state: waveState },
    trigger: { fired: triggerFired, reference: triggerReference },
  }
}

describe('explainSignal', () => {
  it('explains a BUY where every condition, including Wave, matches today', () => {
    const result = explainSignal(
      'BUY',
      screens({ tideTrend: 'BULLISH', impulse: 'GREEN', waveState: 'OVERSOLD_PULLBACK', triggerFired: true }),
    )

    expect(result.conditions.map((c) => c.met)).toEqual([true, true, true, true])
    expect(result.headline).toMatch(/^BUY:/)
    const wave = result.conditions.find((c) => c.key === 'wave')!
    expect(wave.detail).toMatch(/shows an oversold pullback today/)
  })

  it('explains a BUY where Wave qualified on an earlier day, not today (the lookback case)', () => {
    const result = explainSignal(
      'BUY',
      screens({ tideTrend: 'BULLISH', impulse: 'BLUE', waveState: 'NO_WAVE', triggerFired: true }),
    )

    const wave = result.conditions.find((c) => c.key === 'wave')!
    expect(wave.met).toBe(true)
    expect(wave.detail).toMatch(/within the last few trading days/)
  })

  it('explains a SELL where every condition matches today', () => {
    const result = explainSignal(
      'SELL',
      screens({
        tideTrend: 'BEARISH',
        impulse: 'RED',
        waveState: 'OVERBOUGHT_RALLY',
        triggerFired: true,
        triggerReference: 'close_below_prior_low',
      }),
    )

    expect(result.conditions.map((c) => c.met)).toEqual([true, true, true, true])
    expect(result.headline).toMatch(/^SELL:/)
    const wave = result.conditions.find((c) => c.key === 'wave')!
    expect(wave.detail).toMatch(/shows an overbought rally today/)
    const trigger = result.conditions.find((c) => c.key === 'trigger')!
    expect(trigger.detail).toMatch(/close below prior low/i)
  })

  it('explains a HOLD with a Neutral tide as not evaluating the other three screens', () => {
    const result = explainSignal(
      'HOLD',
      screens({ tideTrend: 'NEUTRAL', impulse: 'BLUE', waveState: 'NO_WAVE', triggerFired: false }),
    )

    expect(result.headline).toMatch(/Tide is Neutral/)
    const [tide, impulse, wave, trigger] = result.conditions
    expect(tide.met).toBe(false)
    expect(impulse.met).toBeNull()
    expect(wave.met).toBeNull()
    expect(trigger.met).toBeNull()
  })

  it('explains a HOLD with a directional tide missing exactly the Wave condition (definitively, by elimination)', () => {
    // Tide/Impulse/Trigger all satisfy a would-be BUY; the signal is still
    // HOLD, so Wave must be the one condition that failed its 5-day lookback.
    const result = explainSignal(
      'HOLD',
      screens({ tideTrend: 'BULLISH', impulse: 'GREEN', waveState: 'NO_WAVE', triggerFired: true }),
    )

    const [tide, impulse, wave, trigger] = result.conditions
    expect(tide.met).toBe(true)
    expect(impulse.met).toBe(true)
    expect(trigger.met).toBe(true)
    expect(wave.met).toBe(false)
    expect(wave.detail).toMatch(/has not shown a qualifying oversold pullback in the last 5 trading days/)
    expect(result.headline).toMatch(/missing: Wave pullback\/rally \(Screen 2\)\.$/)
  })

  it('explains a HOLD with a directional tide missing exactly the Trigger condition, leaving Wave honestly uncertain', () => {
    const result = explainSignal(
      'HOLD',
      screens({ tideTrend: 'BULLISH', impulse: 'GREEN', waveState: 'NO_WAVE', triggerFired: false }),
    )

    const [tide, impulse, wave, trigger] = result.conditions
    expect(tide.met).toBe(true)
    expect(impulse.met).toBe(true)
    expect(trigger.met).toBe(false)
    // Wave's true 5-day state genuinely can't be determined from today's
    // reading alone once Trigger already blocks the signal on its own.
    expect(wave.met).toBeNull()
    expect(wave.detail).toMatch(/may have shown one on an earlier day/)
    expect(wave.detail).toMatch(/Trigger.*isn.t met/)
    expect(result.headline).toMatch(/missing: Trigger fired \(Screen 3\)\.$/)
  })

  it('explains a HOLD blocked only by the Impulse gate, with Trigger fired -- Wave stays honestly ambiguous, naming only Impulse as the other blocker', () => {
    const result = explainSignal(
      'HOLD',
      screens({ tideTrend: 'BULLISH', impulse: 'RED', waveState: 'NO_WAVE', triggerFired: true }),
    )

    const [tide, impulse, wave, trigger] = result.conditions
    expect(tide.met).toBe(true)
    expect(impulse.met).toBe(false)
    expect(trigger.met).toBe(true)
    expect(wave.met).toBeNull()
    expect(wave.detail).toMatch(/the Impulse gate also isn.t met/)
    expect(result.headline).toMatch(/missing: Impulse gate\.$/)
  })

  it('explains a HOLD with both the Impulse gate and Trigger already blocking -- uses a plural verb, not "also isn\'t met"', () => {
    const result = explainSignal(
      'HOLD',
      screens({ tideTrend: 'BULLISH', impulse: 'RED', waveState: 'NO_WAVE', triggerFired: false }),
    )

    const wave = result.conditions.find((c) => c.key === 'wave')!
    expect(wave.met).toBeNull()
    expect(wave.detail).toMatch(/the Impulse gate and Trigger also aren.t met/)
    expect(wave.detail).not.toMatch(/also isn.t met/)
  })

  it('gives Trigger a non-contradictory detail when reference is not_applicable despite a directional Tide (fewer than 2 daily bars)', () => {
    const result = explainSignal(
      'HOLD',
      screens({
        tideTrend: 'BULLISH',
        impulse: 'RED',
        waveState: 'NO_WAVE',
        triggerFired: false,
        triggerReference: 'not_applicable',
      }),
    )

    const trigger = result.conditions.find((c) => c.key === 'trigger')!
    expect(trigger.met).toBe(false)
    expect(trigger.detail).not.toMatch(/closed back above the prior high/)
    expect(trigger.detail).not.toMatch(/reference: Not applicable/)
    expect(trigger.detail).toMatch(/enough daily price history/)
  })

  it('gives Trigger a non-contradictory detail on the SELL/BEARISH side too when reference is not_applicable', () => {
    const result = explainSignal(
      'HOLD',
      screens({
        tideTrend: 'BEARISH',
        impulse: 'GREEN',
        waveState: 'NO_WAVE',
        triggerFired: false,
        triggerReference: 'not_applicable',
      }),
    )

    const trigger = result.conditions.find((c) => c.key === 'trigger')!
    expect(trigger.met).toBe(false)
    expect(trigger.detail).not.toMatch(/closed back below the prior low/)
    expect(trigger.detail).not.toMatch(/reference: Not applicable/)
    expect(trigger.detail).toMatch(/enough daily price history yet to compare today.s close against a prior low/)
  })

  it('explains a HOLD where Wave already shows today but the Impulse gate still blocks it', () => {
    const result = explainSignal(
      'HOLD',
      screens({ tideTrend: 'BULLISH', impulse: 'RED', waveState: 'OVERSOLD_PULLBACK', triggerFired: true }),
    )

    const [tide, impulse, wave, trigger] = result.conditions
    expect(tide.met).toBe(true)
    expect(wave.met).toBe(true)
    expect(wave.detail).toMatch(/shows an oversold pullback today/)
    expect(impulse.met).toBe(false)
    expect(trigger.met).toBe(true)
    expect(result.headline).toMatch(/missing: Impulse gate\.$/)
  })

  it('explains a HOLD where Wave already shows today but both Impulse and Trigger still block it', () => {
    const result = explainSignal(
      'HOLD',
      screens({ tideTrend: 'BULLISH', impulse: 'RED', waveState: 'OVERSOLD_PULLBACK', triggerFired: false }),
    )

    const [tide, impulse, wave, trigger] = result.conditions
    expect(tide.met).toBe(true)
    expect(wave.met).toBe(true)
    expect(wave.detail).toMatch(/shows an oversold pullback today/)
    expect(impulse.met).toBe(false)
    expect(trigger.met).toBe(false)
    expect(result.headline).toMatch(/missing: Impulse gate, Trigger fired \(Screen 3\)\.$/)
  })

  it('explains a HOLD blocked by the Impulse gate on the SELL side', () => {
    const result = explainSignal(
      'HOLD',
      screens({
        tideTrend: 'BEARISH',
        impulse: 'GREEN',
        waveState: 'NO_WAVE',
        triggerFired: false,
        triggerReference: 'close_below_prior_low',
      }),
    )

    const [tide, impulse] = result.conditions
    expect(tide.met).toBe(true)
    expect(impulse.met).toBe(false)
    expect(impulse.detail).toMatch(/blocks any fresh SELL/)
    expect(result.headline).toMatch(/Impulse gate/)
    expect(result.headline).toMatch(/Trigger fired \(Screen 3\)/)
  })
})
