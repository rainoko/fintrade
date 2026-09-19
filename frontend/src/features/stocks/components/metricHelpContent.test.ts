import { describe, expect, it } from 'vitest'
import type { SupportResistanceZone } from '../../../api/stocks'
import {
  bearPowerHelp,
  bullPowerHelp,
  channelHelp,
  confidenceHelp,
  ema13Help,
  ema26Help,
  falseBreakoutHelp,
  getConfidenceComponentHelp,
  impulseHelp,
  macdHistogramHelp,
  signalHelp,
  supportResistanceZoneHelp,
  tideHelp,
  triggerHelp,
  valueZoneHelp,
  waveHelp,
} from './metricHelpContent'

function buildZone(
  overrides: Partial<SupportResistanceZone> = {},
): SupportResistanceZone {
  return {
    role: 'resistance',
    upper: 236.9,
    lower: 233.4,
    first_touch_date: '2026-06-02',
    last_touch_date: '2026-08-14',
    touch_count: 3,
    length_days: 73,
    length_category: 'intermediate',
    height_pct: 1.5,
    height_category: 'minor',
    dollar_volume: 12_400_000_000,
    strength_score: 50,
    broken: false,
    break_date: null,
    false_breakout: null,
    ...overrides,
  }
}

describe('metricHelpContent', () => {
  describe('signalHelp.interpretValue', () => {
    it('describes BUY, SELL, and HOLD distinctly', () => {
      expect(signalHelp.interpretValue('BUY')).toMatch(/bullish/)
      expect(signalHelp.interpretValue('SELL')).toMatch(/bearish/)
      expect(signalHelp.interpretValue('HOLD')).toMatch(/unmet/)
    })
  })

  describe('confidenceHelp.interpretValue', () => {
    it('renders the raw percentage alongside the band, at the 0/100 boundaries', () => {
      expect(confidenceHelp.interpretValue(0, 'Low')).toBe(
        'Currently 0% -- Low confidence.',
      )
      expect(confidenceHelp.interpretValue(100, 'High')).toBe(
        'Currently 100% -- High confidence.',
      )
    })

    it('rounds a fractional confidence value', () => {
      expect(confidenceHelp.interpretValue(72.4, 'High')).toBe(
        'Currently 72% -- High confidence.',
      )
    })
  })

  describe('confidence breakdown component lookup', () => {
    it('finds all five documented components and computes their contribution', () => {
      const tide = getConfidenceComponentHelp('tide_alignment')
      expect(tide).toBeDefined()
      expect(tide?.interpretValue(1.0, 0.3)).toBe(
        'Currently scored 100% at a 30% weight -- contributing 30 of the 100 possible confidence points.',
      )

      for (const key of [
        'impulse_gate',
        'oscillator_extremity',
        'elder_ray_confirmation',
        'volume_confirmation',
      ]) {
        expect(getConfidenceComponentHelp(key)).toBeDefined()
      }
    })

    it('returns undefined for an undocumented future component name', () => {
      expect(getConfidenceComponentHelp('future_component')).toBeUndefined()
    })
  })

  describe('tideHelp.interpretValue', () => {
    it('names the allowed action for a Bullish tide', () => {
      expect(tideHelp.interpretValue('BULLISH', 'rising')).toBe(
        'Currently Bullish (weekly MACD-H slope rising) -- only fresh buy signals are considered while the tide holds this direction.',
      )
    })

    it('names the allowed action for a Bearish tide', () => {
      expect(tideHelp.interpretValue('BEARISH', 'falling')).toBe(
        'Currently Bearish (weekly MACD-H slope falling) -- only fresh sell signals are considered while the tide holds this direction.',
      )
    })

    it('explains a Neutral tide with a flat slope by naming both possible causes (flat slope or too little weekly history), not asserting one', () => {
      const message = tideHelp.interpretValue('NEUTRAL', 'flat')
      expect(message).toMatch(/no directional Triple Screen setup/)
      // 'flat' is also reported by evaluate_tide's <2-weekly-bar short-circuit,
      // which never computes a slope at all -- see this task's `decisions`
      // entry. Assert both candidate causes are named rather than just one.
      expect(message).toMatch(/enough weekly price history/)
      expect(message).toMatch(/genuinely flat/)
    })

    it('omits the raw "slope Flat" parenthetical in the flat-slope Neutral case, since asserting it unqualified would contradict the hedge in the same sentence', () => {
      const message = tideHelp.interpretValue('NEUTRAL', 'flat')
      expect(message).not.toMatch(/weekly MACD-H slope Flat/)
      expect(message.startsWith('Currently Neutral --')).toBe(true)
    })

    it('explains a Neutral tide with a rising/falling slope as a slope-vs-EMA disagreement', () => {
      const message = tideHelp.interpretValue('NEUTRAL', 'rising')
      expect(message).toMatch(/no directional Triple Screen setup/)
      expect(message).toMatch(/slope and EMA13\/26 relationship disagree/)
    })
  })

  describe('impulseHelp.interpretValue', () => {
    it('describes GREEN as blocking fresh SELL only', () => {
      expect(impulseHelp.interpretValue('GREEN')).toMatch(/BUY or HOLD is allowed/)
    })

    it('describes RED as blocking fresh BUY only', () => {
      expect(impulseHelp.interpretValue('RED')).toMatch(/SELL or HOLD is allowed/)
    })

    it('describes BLUE as weaker but unblocked', () => {
      expect(impulseHelp.interpretValue('BLUE')).toMatch(/disagree/)
    })
  })

  describe('waveHelp.interpretValue', () => {
    it('reads a Stochastic %K of 36.9 as neutral (matching the task description’s own example)', () => {
      const result = waveHelp.interpretValue(36.9, -100, 'RANGING')
      expect(result).toContain(
        'Stochastic %K of 36.9 is in the neutral zone (30-70): neither overbought nor oversold',
      )
    })

    it('reads exactly 30 as not oversold (oversold is strictly below 30)', () => {
      const result = waveHelp.interpretValue(30, 0, 'RANGING')
      expect(result).toContain('neutral zone')
    })

    it('reads exactly 70 as not overbought (overbought is strictly above 70)', () => {
      const result = waveHelp.interpretValue(70, 0, 'RANGING')
      expect(result).toContain('neutral zone')
    })

    it('reads below 30 as oversold', () => {
      expect(waveHelp.interpretValue(24.3, -18234.5, 'OVERSOLD_PULLBACK')).toContain(
        'Stochastic %K of 24.3 is oversold (below 30)',
      )
    })

    it('reads above 70 as overbought', () => {
      expect(waveHelp.interpretValue(78.1, 15234.2, 'OVERBOUGHT_RALLY')).toContain(
        'Stochastic %K of 78.1 is overbought (above 70)',
      )
    })

    it('handles a null/undefined stochastic reading without throwing', () => {
      expect(() => waveHelp.interpretValue(null, null, 'RANGING')).not.toThrow()
      expect(waveHelp.interpretValue(undefined, undefined, 'RANGING')).toContain(
        'unavailable',
      )
    })
  })

  describe('triggerHelp.interpretValue', () => {
    it('describes a fired trigger with its reference', () => {
      expect(
        triggerHelp.interpretValue(true, 'close_above_prior_high', 'BULLISH'),
      ).toContain('Fired -- Close above prior high')
    })

    it('describes a not_applicable trigger caused by a Neutral tide (the common case)', () => {
      expect(triggerHelp.interpretValue(false, 'not_applicable', 'NEUTRAL')).toMatch(
        /Tide is Neutral/,
      )
    })

    it('describes a not_applicable trigger caused by genuinely insufficient daily history (the rare edge case, tide not Neutral)', () => {
      expect(triggerHelp.interpretValue(false, 'not_applicable', 'BULLISH')).toMatch(
        /enough daily price history/,
      )
    })

    it('describes an unfired trigger with a reference', () => {
      expect(triggerHelp.interpretValue(false, 'no_trigger', 'BULLISH')).toBe(
        'Not fired yet -- reference: No trigger.',
      )
    })
  })

  describe('EMA 13/26 interpretValue', () => {
    it('reads EMA13 above EMA26 as an uptrend', () => {
      expect(ema13Help.interpretValue(226.4, 221.7)).toContain('an uptrend reading')
      expect(ema26Help.interpretValue(221.7, 226.4)).toMatch(/above it/)
    })

    it('reads EMA13 below EMA26 as a downtrend', () => {
      expect(ema13Help.interpretValue(200, 210)).toContain('a downtrend reading')
    })

    it('handles a missing value without throwing', () => {
      expect(ema13Help.interpretValue(null, 210)).toMatch(/unavailable/)
      expect(ema13Help.interpretValue(200, null)).toBe('Currently 200.00.')
      expect(ema26Help.interpretValue(null, 210)).toMatch(/unavailable/)
      expect(ema26Help.interpretValue(200, null)).toBe('Currently 200.00.')
    })
  })

  describe('macdHistogramHelp.interpretValue', () => {
    it('reads a positive value as bullish momentum', () => {
      expect(macdHistogramHelp.interpretValue(1.82)).toMatch(/bullish momentum/)
    })

    it('reads a negative value as bearish momentum', () => {
      expect(macdHistogramHelp.interpretValue(-1.82)).toMatch(/bearish momentum/)
    })

    it('reads exactly zero distinctly', () => {
      expect(macdHistogramHelp.interpretValue(0)).toBe(
        'Currently 0.00 -- MACD is exactly at its signal line.',
      )
    })

    it('handles a missing value without throwing', () => {
      expect(macdHistogramHelp.interpretValue(null)).toMatch(/unavailable/)
    })
  })

  describe('bullPowerHelp / bearPowerHelp interpretValue', () => {
    it('reads positive Bull Power as buyers pushing above EMA(13)', () => {
      expect(bullPowerHelp.interpretValue(3.1)).toMatch(/buyers pushed price above/)
    })

    it('reads negative Bull Power as buyers failing to push above EMA(13)', () => {
      expect(bullPowerHelp.interpretValue(-1.2)).toMatch(/couldn.t push price above/)
    })

    it('reads negative Bear Power as the normal/expected uptrend reading', () => {
      expect(bearPowerHelp.interpretValue(-1.4)).toMatch(/normal\/expected reading/)
    })

    it('reads positive Bear Power as an unusually strong bullish reading', () => {
      expect(bearPowerHelp.interpretValue(0.5)).toMatch(
        /unusually strong bullish reading/,
      )
    })

    it('handles a missing value without throwing', () => {
      expect(bullPowerHelp.interpretValue(undefined)).toMatch(/unavailable/)
      expect(bearPowerHelp.interpretValue(Number.NaN)).toMatch(/unavailable/)
    })
  })

  describe('channelHelp.interpretValue', () => {
    it('reports the warm-up window when the channel bounds are unavailable', () => {
      expect(channelHelp.interpretValue(null, null, 229.7)).toMatch(/warm-up window/)
      expect(channelHelp.interpretValue(233.3, undefined, 229.7)).toMatch(
        /warm-up window/,
      )
    })

    it('reports just the bounds when the latest close is unavailable', () => {
      expect(channelHelp.interpretValue(233.3, 219.5, null)).toBe(
        'Currently 219.50-233.30 (±3.0% around EMA(13)).',
      )
    })

    it('reads the latest close at/above the upper band as the profit-taking zone', () => {
      expect(channelHelp.interpretValue(233.3, 219.5, 235.0)).toMatch(
        /profit-taking\/overextension zone/,
      )
    })

    it('reads the latest close at/above the upper band at the exact boundary too', () => {
      expect(channelHelp.interpretValue(233.3, 219.5, 233.3)).toMatch(
        /profit-taking\/overextension zone/,
      )
    })

    it('reads the latest close at/below the lower band as the contrarian buying zone', () => {
      expect(channelHelp.interpretValue(233.3, 219.5, 215.0)).toMatch(
        /contrarian buying zone/,
      )
    })

    it('reads the latest close at/below the lower band at the exact boundary too', () => {
      expect(channelHelp.interpretValue(233.3, 219.5, 219.5)).toMatch(
        /contrarian buying zone/,
      )
    })

    it('reads a latest close inside the channel as a percentage position between the bands', () => {
      const message = channelHelp.interpretValue(233.3, 219.5, 229.7)
      expect(message).toMatch(/229\.70/)
      expect(message).toMatch(/inside the channel/)
    })
  })

  describe('valueZoneHelp.interpretValue', () => {
    it('handles a missing EMA value without throwing', () => {
      expect(valueZoneHelp.interpretValue(null, 221.7)).toMatch(/unavailable/)
      expect(valueZoneHelp.interpretValue(226.4, undefined)).toMatch(/unavailable/)
    })

    it('reads EMA13 above EMA26 as an uptrend, with the bounds in ascending order', () => {
      expect(valueZoneHelp.interpretValue(226.4, 221.7)).toBe(
        'Currently 221.70-226.40 (EMA13 above EMA26 -- an uptrend reading).',
      )
    })

    it('reads EMA13 below EMA26 as a downtrend, with the bounds still in ascending order', () => {
      expect(valueZoneHelp.interpretValue(219.0, 221.7)).toBe(
        'Currently 219.00-221.70 (EMA13 below EMA26 -- a downtrend reading).',
      )
    })

    it('reads EMA13 exactly equal to EMA26 as a flat reading', () => {
      expect(valueZoneHelp.interpretValue(220.0, 220.0)).toBe(
        'Currently 220.00-220.00 (EMA13 equal to EMA26 -- a flat reading).',
      )
    })
  })

  describe('supportResistanceZoneHelp.interpretValue', () => {
    it('reports no zones detected when the list is empty', () => {
      expect(supportResistanceZoneHelp.interpretValue([], 0, 229.7)).toBe(
        'No support/resistance zones detected yet for this ticker -- needs at least 2 clustered swing-point touches spanning 14+ days.',
      )
    })

    it('reports the displayed/detected count without a nearest-zone reading when latestClose is unknown', () => {
      const zones = [buildZone()]
      expect(supportResistanceZoneHelp.interpretValue(zones, 1, undefined)).toBe(
        'Showing 1 of 1 detected zone (strongest first).',
      )
      expect(supportResistanceZoneHelp.interpretValue(zones, 1, null)).toBe(
        'Showing 1 of 1 detected zone (strongest first).',
      )
    })

    it('pluralizes "zone(s)" correctly for a single vs. multiple detected zones', () => {
      const oneZone = [buildZone()]
      const twoZones = [buildZone(), buildZone({ upper: 210, lower: 205 })]
      expect(supportResistanceZoneHelp.interpretValue(oneZone, 1, undefined)).toMatch(
        /1 detected zone \(/,
      )
      expect(supportResistanceZoneHelp.interpretValue(twoZones, 2, undefined)).toMatch(
        /2 detected zones \(/,
      )
    })

    it('identifies the zone nearest the latest close among several, by distance to its nearer edge', () => {
      const resistance = buildZone({ role: 'resistance', upper: 231.0, lower: 229.9 })
      const support = buildZone({ role: 'support', upper: 210.0, lower: 205.0 })
      const message = supportResistanceZoneHelp.interpretValue(
        [resistance, support],
        2,
        229.7,
      )
      expect(message).toMatch(
        /Nearest to the latest close \(229\.70\): Resistance 229\.90-231\.00/,
      )
    })

    it('treats a latest close inside a zone as distance 0 to that zone, over a farther-but-still-close one', () => {
      const containing = buildZone({ role: 'support', upper: 231.0, lower: 228.0 })
      const nearButOutside = buildZone({
        role: 'resistance',
        upper: 229.9,
        lower: 229.85,
      })
      const message = supportResistanceZoneHelp.interpretValue(
        [containing, nearButOutside],
        2,
        229.7,
      )
      expect(message).toMatch(/Support 228\.00-231\.00/)
    })

    it('notes when the nearest zone has flipped role after a confirmed break', () => {
      const zone = buildZone({ broken: true, break_date: '2026-08-01' })
      const message = supportResistanceZoneHelp.interpretValue([zone], 1, 235.0)
      expect(message).toMatch(/role flipped after a confirmed break/)
    })

    it('omits the role-flipped clause for a zone that has never broken', () => {
      const zone = buildZone({ broken: false })
      const message = supportResistanceZoneHelp.interpretValue([zone], 1, 235.0)
      expect(message).not.toMatch(/role flipped/)
    })
  })

  describe('falseBreakoutHelp.interpretValue', () => {
    it('reports no false breakouts when none of the zones have one', () => {
      const zones = [buildZone(), buildZone({ upper: 210, lower: 205 })]
      expect(falseBreakoutHelp.interpretValue(zones)).toBe(
        'No false breakouts detected among these zones right now.',
      )
    })

    it("describes an 'up' false breakout as a break above followed by a close back inside", () => {
      const zone = buildZone({
        role: 'resistance',
        upper: 236.9,
        lower: 233.4,
        false_breakout: {
          direction: 'up',
          breakout_date: '2026-08-20',
          reentry_date: '2026-09-02',
          extreme_price: 238.5,
        },
      })
      const message = falseBreakoutHelp.interpretValue([zone])
      expect(message).toBe(
        "Most recent: the resistance zone 233.40-236.90 broke above it on 2026-08-20, then closed back inside by 2026-09-02 -- suggested stop near 238.50, the failed move's own extreme.",
      )
    })

    it("describes a 'down' false breakout as a break below followed by a close back inside", () => {
      const zone = buildZone({
        role: 'support',
        upper: 210.0,
        lower: 205.0,
        false_breakout: {
          direction: 'down',
          breakout_date: '2026-08-20',
          reentry_date: '2026-09-02',
          extreme_price: 203.5,
        },
      })
      const message = falseBreakoutHelp.interpretValue([zone])
      expect(message).toMatch(/support zone 205\.00-210\.00 broke below it/)
      expect(message).toMatch(/stop near 203\.50/)
    })

    it('picks the most recent false breakout (by reentry_date) among several zones that have one', () => {
      const older = buildZone({
        role: 'resistance',
        upper: 236.9,
        lower: 233.4,
        false_breakout: {
          direction: 'up',
          breakout_date: '2026-07-01',
          reentry_date: '2026-07-05',
          extreme_price: 238.0,
        },
      })
      const newer = buildZone({
        role: 'support',
        upper: 210.0,
        lower: 205.0,
        false_breakout: {
          direction: 'down',
          breakout_date: '2026-08-20',
          reentry_date: '2026-09-02',
          extreme_price: 203.5,
        },
      })
      const message = falseBreakoutHelp.interpretValue([older, newer])
      expect(message).toMatch(/support zone 205\.00-210\.00/)
      expect(message).toMatch(/203\.50/)
    })

    it('keeps the already-found most recent breakout when a later zone in the list is older, not just when it happens to be first', () => {
      // Same fixtures as above, reversed order -- exercises the `reduce`
      // callback's "keep the current accumulator" branch (the newer zone,
      // now first, must stay the accumulator when compared against the
      // older one that now comes second), not just the "replace it" branch
      // the order above exercises.
      const older = buildZone({
        role: 'resistance',
        upper: 236.9,
        lower: 233.4,
        false_breakout: {
          direction: 'up',
          breakout_date: '2026-07-01',
          reentry_date: '2026-07-05',
          extreme_price: 238.0,
        },
      })
      const newer = buildZone({
        role: 'support',
        upper: 210.0,
        lower: 205.0,
        false_breakout: {
          direction: 'down',
          breakout_date: '2026-08-20',
          reentry_date: '2026-09-02',
          extreme_price: 203.5,
        },
      })
      const message = falseBreakoutHelp.interpretValue([newer, older])
      expect(message).toMatch(/support zone 205\.00-210\.00/)
      expect(message).toMatch(/203\.50/)
    })
  })
})
