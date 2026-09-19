import { describe, expect, it } from 'vitest'
import type { Screens } from '../../../api/stocks'
import { explainSignal } from './signalExplanation'

function screens(
  overrides: Partial<{
    tideTrend: Screens['tide']['trend']
    weeklySlope: Screens['tide']['weekly_macd_histogram_slope']
    impulse: Screens['impulse']
    waveState: string
    showedPullbackInLookback: boolean | null
    showedRallyInLookback: boolean | null
    triggerFired: boolean
    triggerReference: string
  }>,
): Screens {
  const {
    tideTrend = 'BULLISH',
    weeklySlope = 'rising',
    impulse = 'GREEN',
    waveState = 'OVERSOLD_PULLBACK',
    // Defaults mirror the target-side lookback boolean matching `waveState`'s
    // default (OVERSOLD_PULLBACK, the BULLISH/BUY side) so tests that don't
    // care about the lookback distinction still get a self-consistent
    // fixture; every test that *does* care overrides these explicitly.
    showedPullbackInLookback = tideTrend === 'NEUTRAL' ? null : tideTrend === 'BULLISH',
    showedRallyInLookback = tideTrend === 'NEUTRAL' ? null : tideTrend === 'BEARISH',
    triggerFired = true,
    triggerReference = 'close_above_prior_high',
  } = overrides
  return {
    tide: { trend: tideTrend, weekly_macd_histogram_slope: weeklySlope },
    impulse,
    wave: {
      stochastic_k: 24.3,
      force_index_2ema: -18234.5,
      state: waveState,
      showed_pullback_in_lookback: showedPullbackInLookback,
      showed_rally_in_lookback: showedRallyInLookback,
    },
    trigger: { fired: triggerFired, reference: triggerReference },
  }
}

describe('explainSignal', () => {
  it('explains a BUY where every condition, including Wave, matches today', () => {
    const result = explainSignal(
      'BUY',
      screens({
        tideTrend: 'BULLISH',
        impulse: 'GREEN',
        waveState: 'OVERSOLD_PULLBACK',
        triggerFired: true,
      }),
    )

    expect(result.conditions.map((c) => c.met)).toEqual([true, true, true, true])
    expect(result.headline).toMatch(/^BUY:/)
    const wave = result.conditions.find((c) => c.key === 'wave')!
    expect(wave.detail).toMatch(/shows an oversold pullback today/)
  })

  it('explains a BUY where Wave qualified on an earlier day, not today (the lookback case)', () => {
    const result = explainSignal(
      'BUY',
      screens({
        tideTrend: 'BULLISH',
        impulse: 'BLUE',
        waveState: 'NO_WAVE',
        showedPullbackInLookback: true,
        triggerFired: true,
      }),
    )

    const wave = result.conditions.find((c) => c.key === 'wave')!
    expect(wave.met).toBe(true)
    expect(wave.detail).toMatch(/within the last 5 trading days/)
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

  it('explains a HOLD with a Neutral tide (slope disagreeing with EMA13/26) as not evaluating the other three screens', () => {
    const result = explainSignal(
      'HOLD',
      screens({
        tideTrend: 'NEUTRAL',
        weeklySlope: 'rising',
        impulse: 'BLUE',
        waveState: 'NO_WAVE',
        triggerFired: false,
      }),
    )

    expect(result.headline).toMatch(/Tide is Neutral/)
    const [tide, impulse, wave, trigger] = result.conditions
    expect(tide.met).toBe(false)
    expect(tide.detail).toMatch(/13\/26-week EMA relationship disagree/)
    expect(impulse.met).toBeNull()
    expect(wave.met).toBeNull()
    expect(trigger.met).toBeNull()
  })

  it('explains a HOLD with a Neutral tide and a flat weekly slope by naming both possible causes (flat slope or too little weekly history), not asserting one', () => {
    const result = explainSignal(
      'HOLD',
      screens({
        tideTrend: 'NEUTRAL',
        weeklySlope: 'flat',
        impulse: 'BLUE',
        waveState: 'NO_WAVE',
        triggerFired: false,
      }),
    )

    // 'flat' is also reported by evaluate_tide's <2-weekly-bar short-circuit
    // (backend/app/signals/triple_screen.py), which never computes a slope
    // at all -- see this task's `decisions` entry.
    const tide = result.conditions.find((c) => c.key === 'tide')!
    expect(tide.met).toBe(false)
    expect(tide.detail).toMatch(/enough weekly price history/)
    expect(tide.detail).toMatch(/genuinely flat/)
    expect(tide.detail).not.toMatch(/relationship disagree/)
  })

  it('explains a HOLD with a directional tide missing exactly the Wave condition (definitively, by elimination)', () => {
    // Tide/Impulse/Trigger all satisfy a would-be BUY; the signal is still
    // HOLD, so Wave must be the one condition that failed its 5-day lookback.
    const result = explainSignal(
      'HOLD',
      screens({
        tideTrend: 'BULLISH',
        impulse: 'GREEN',
        waveState: 'NO_WAVE',
        showedPullbackInLookback: false,
        triggerFired: true,
      }),
    )

    const [tide, impulse, wave, trigger] = result.conditions
    expect(tide.met).toBe(true)
    expect(impulse.met).toBe(true)
    expect(trigger.met).toBe(true)
    expect(wave.met).toBe(false)
    expect(wave.detail).toMatch(
      /has not shown a qualifying oversold pullback in the last 5 trading days/,
    )
    expect(result.headline).toMatch(/missing: Wave pullback\/rally \(Screen 2\)\.$/)
  })

  it('explains a HOLD blocked only by Trigger, with Wave definitively having shown the qualifying state within its lookback (no longer ambiguous)', () => {
    const result = explainSignal(
      'HOLD',
      screens({
        tideTrend: 'BULLISH',
        impulse: 'GREEN',
        waveState: 'NO_WAVE',
        showedPullbackInLookback: true,
        triggerFired: false,
      }),
    )

    const [tide, impulse, wave, trigger] = result.conditions
    expect(tide.met).toBe(true)
    expect(impulse.met).toBe(true)
    expect(trigger.met).toBe(false)
    // The lookback boolean is read directly -- Wave definitively showed the
    // qualifying state on an earlier day, even though today's own reading
    // (NO_WAVE) doesn't show it, and even though Trigger is what's actually
    // blocking a fresh BUY right now.
    expect(wave.met).toBe(true)
    expect(wave.detail).toMatch(/within the last 5 trading days/)
    expect(result.headline).toMatch(/missing: Trigger fired \(Screen 3\)\.$/)
  })

  it('explains a HOLD blocked by both Wave and Trigger when Wave never showed the qualifying state in its lookback either', () => {
    const result = explainSignal(
      'HOLD',
      screens({
        tideTrend: 'BULLISH',
        impulse: 'GREEN',
        waveState: 'NO_WAVE',
        showedPullbackInLookback: false,
        triggerFired: false,
      }),
    )

    const [tide, impulse, wave, trigger] = result.conditions
    expect(tide.met).toBe(true)
    expect(impulse.met).toBe(true)
    expect(trigger.met).toBe(false)
    expect(wave.met).toBe(false)
    expect(wave.detail).toMatch(/has not shown a qualifying oversold pullback/)
    expect(result.headline).toMatch(
      /missing: Wave pullback\/rally \(Screen 2\), Trigger fired \(Screen 3\)\.$/,
    )
  })

  it('explains a HOLD blocked only by the Impulse gate, with Trigger fired and Wave definitively having shown the qualifying state (no longer ambiguous)', () => {
    const result = explainSignal(
      'HOLD',
      screens({
        tideTrend: 'BULLISH',
        impulse: 'RED',
        waveState: 'NO_WAVE',
        showedPullbackInLookback: true,
        triggerFired: true,
      }),
    )

    const [tide, impulse, wave, trigger] = result.conditions
    expect(tide.met).toBe(true)
    expect(impulse.met).toBe(false)
    expect(trigger.met).toBe(true)
    expect(wave.met).toBe(true)
    expect(wave.detail).toMatch(/within the last 5 trading days/)
    expect(result.headline).toMatch(/missing: Impulse gate\.$/)
  })

  it('explains a HOLD blocked by both the Impulse gate and Wave, with Trigger fired', () => {
    const result = explainSignal(
      'HOLD',
      screens({
        tideTrend: 'BULLISH',
        impulse: 'RED',
        waveState: 'NO_WAVE',
        showedPullbackInLookback: false,
        triggerFired: true,
      }),
    )

    const [tide, impulse, wave, trigger] = result.conditions
    expect(tide.met).toBe(true)
    expect(impulse.met).toBe(false)
    expect(trigger.met).toBe(true)
    expect(wave.met).toBe(false)
    expect(result.headline).toMatch(
      /missing: Impulse gate, Wave pullback\/rally \(Screen 2\)\.$/,
    )
  })

  it('treats a null lookback boolean on a directional Tide as not-met (defensive fallback; the API contract never actually sends this)', () => {
    const result = explainSignal(
      'HOLD',
      screens({
        tideTrend: 'BULLISH',
        impulse: 'GREEN',
        waveState: 'NO_WAVE',
        showedPullbackInLookback: null,
        triggerFired: true,
      }),
    )

    const wave = result.conditions.find((c) => c.key === 'wave')!
    expect(wave.met).toBe(false)
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
    expect(trigger.detail).toMatch(
      /enough daily price history yet to compare today.s close against a prior low/,
    )
  })

  it('explains a HOLD where Wave already shows today but the Impulse gate still blocks it', () => {
    const result = explainSignal(
      'HOLD',
      screens({
        tideTrend: 'BULLISH',
        impulse: 'RED',
        waveState: 'OVERSOLD_PULLBACK',
        triggerFired: true,
      }),
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
      screens({
        tideTrend: 'BULLISH',
        impulse: 'RED',
        waveState: 'OVERSOLD_PULLBACK',
        triggerFired: false,
      }),
    )

    const [tide, impulse, wave, trigger] = result.conditions
    expect(tide.met).toBe(true)
    expect(wave.met).toBe(true)
    expect(wave.detail).toMatch(/shows an oversold pullback today/)
    expect(impulse.met).toBe(false)
    expect(trigger.met).toBe(false)
    expect(result.headline).toMatch(
      /missing: Impulse gate, Trigger fired \(Screen 3\)\.$/,
    )
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

  it('explains a HOLD blocked only by Trigger on the SELL side, with Wave definitively having shown the qualifying state within its lookback (no longer ambiguous)', () => {
    // Mirrors the BULLISH-side "blocked only by Trigger" case above, but
    // exercises the showed_rally_in_lookback arm of explainSignal's
    // isBuySide ternary instead of showed_pullback_in_lookback.
    const result = explainSignal(
      'HOLD',
      screens({
        tideTrend: 'BEARISH',
        impulse: 'RED',
        waveState: 'NO_WAVE',
        showedRallyInLookback: true,
        triggerFired: false,
        triggerReference: 'close_below_prior_low',
      }),
    )

    const [tide, impulse, wave, trigger] = result.conditions
    expect(tide.met).toBe(true)
    expect(impulse.met).toBe(true)
    expect(trigger.met).toBe(false)
    // The lookback boolean is read directly -- Wave definitively showed the
    // qualifying overbought rally on an earlier day, even though today's own
    // reading (NO_WAVE) doesn't show it, and even though Trigger is what's
    // actually blocking a fresh SELL right now.
    expect(wave.met).toBe(true)
    expect(wave.detail).toMatch(/within the last 5 trading days/)
    expect(result.headline).toMatch(/missing: Trigger fired \(Screen 3\)\.$/)
  })

  it('explains a HOLD blocked by both Wave and Trigger on the SELL side when Wave never showed the qualifying rally in its lookback either', () => {
    // Mirrors the BULLISH-side "blocked by both Wave and Trigger" case
    // above, on the showed_rally_in_lookback arm instead.
    const result = explainSignal(
      'HOLD',
      screens({
        tideTrend: 'BEARISH',
        impulse: 'RED',
        waveState: 'NO_WAVE',
        showedRallyInLookback: false,
        triggerFired: false,
        triggerReference: 'close_below_prior_low',
      }),
    )

    const [tide, impulse, wave, trigger] = result.conditions
    expect(tide.met).toBe(true)
    expect(impulse.met).toBe(true)
    expect(trigger.met).toBe(false)
    expect(wave.met).toBe(false)
    expect(wave.detail).toMatch(/has not shown a qualifying overbought rally/)
    expect(result.headline).toMatch(
      /missing: Wave pullback\/rally \(Screen 2\), Trigger fired \(Screen 3\)\.$/,
    )
  })

  it('explains a HOLD blocked only by the Impulse gate on the SELL side, with Trigger fired and Wave definitively having shown the qualifying rally (no longer ambiguous)', () => {
    // Mirrors the BULLISH-side "blocked only by the Impulse gate" case
    // above, on the showed_rally_in_lookback arm instead.
    const result = explainSignal(
      'HOLD',
      screens({
        tideTrend: 'BEARISH',
        impulse: 'GREEN',
        waveState: 'NO_WAVE',
        showedRallyInLookback: true,
        triggerFired: true,
        triggerReference: 'close_below_prior_low',
      }),
    )

    const [tide, impulse, wave, trigger] = result.conditions
    expect(tide.met).toBe(true)
    expect(impulse.met).toBe(false)
    expect(trigger.met).toBe(true)
    expect(wave.met).toBe(true)
    expect(wave.detail).toMatch(/within the last 5 trading days/)
    expect(result.headline).toMatch(/missing: Impulse gate\.$/)
  })
})
