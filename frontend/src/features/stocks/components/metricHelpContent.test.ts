import { describe, expect, it } from 'vitest'
import {
  bearPowerHelp,
  bullPowerHelp,
  confidenceHelp,
  ema13Help,
  ema26Help,
  getConfidenceComponentHelp,
  impulseHelp,
  macdHistogramHelp,
  signalHelp,
  tideHelp,
  triggerHelp,
  waveHelp,
} from './metricHelpContent'

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
})
