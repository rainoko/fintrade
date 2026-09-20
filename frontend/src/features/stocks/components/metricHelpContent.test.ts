import { describe, expect, it } from 'vitest'
import type {
  DivergenceOut,
  HistoryResponse,
  IndicatorHistoryPoint,
  InsiderClusterOut,
  KangarooTailOut,
  ProfitTargetOut,
  SupportResistanceZone,
} from '../../../api/stocks'
import {
  accumulationDistributionHelp,
  adxHelp,
  atrHelp,
  bearPowerHelp,
  bullPowerHelp,
  channelHelp,
  confidenceHelp,
  countTideTrends,
  directionalSystemHelp,
  divergenceHelp,
  earningsDateHelp,
  ema13Help,
  ema26Help,
  exDividendDateHelp,
  falseBreakoutHelp,
  fundamentalDataUnavailableHelp,
  getConfidenceComponentHelp,
  impulseHelp,
  insiderClustersHelp,
  insiderTransactionsHelp,
  kangarooTailHelp,
  macdHistogramHelp,
  obvHelp,
  profitTargetHelp,
  rsiHelp,
  seasonHelp,
  shortInterestHelp,
  signalHelp,
  supportResistanceZoneHelp,
  tideHelp,
  tideRegionHelp,
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

  describe('profitTargetHelp.interpretValue', () => {
    const target: ProfitTargetOut = {
      price: 245.0,
      source: 'channel',
      distance_to_stop: 9.3,
      distance_to_target: 18.6,
      reward_risk_ratio: 2.0,
      meets_minimum_reward_risk: true,
    }

    it('explains a null signal (couldn’t be computed) distinctly from a definite non-BUY signal', () => {
      expect(profitTargetHelp.interpretValue(null, null)).toMatch(/couldn’t be computed/)
    })

    it('explains a non-BUY signal by name', () => {
      expect(profitTargetHelp.interpretValue(null, 'SELL')).toBe(
        'Not applicable -- a profit target is only ever computed for a fresh BUY signal; this ticker is currently SELL.',
      )
    })

    it('explains a BUY signal with no current candidate', () => {
      expect(profitTargetHelp.interpretValue(null, 'BUY')).toMatch(
        /Currently unavailable for this BUY signal/,
      )
    })

    it('names the channel technique and reward:risk ratio, and confirms it clears the 2:1 minimum', () => {
      const text = profitTargetHelp.interpretValue(target, 'BUY')
      expect(text).toContain('Currently 245.00, from the channel/Tradebill formula')
      expect(text).toContain('Reward:risk ratio 2.0:1')
      expect(text).toContain('This clears Elder’s 2:1 minimum.')
    })

    it('names the support/resistance technique and flags a ratio that fails the 2:1 minimum', () => {
      const text = profitTargetHelp.interpretValue(
        {
          ...target,
          source: 'support_resistance',
          reward_risk_ratio: 0.9,
          meets_minimum_reward_risk: false,
        },
        'BUY',
      )
      expect(text).toContain('nearest detected support/resistance zone')
      expect(text).toContain('This FAILS Elder’s 2:1 minimum')
    })

    it('explains an undefined ratio (stop distance <= 0) instead of a fabricated number', () => {
      const text = profitTargetHelp.interpretValue(
        { ...target, reward_risk_ratio: null, meets_minimum_reward_risk: false },
        'BUY',
      )
      expect(text).toMatch(/reward:risk ratio is undefined right now/)
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
      expect(message).toMatch(/too small to call clearly rising or falling/)
    })

    it('omits the raw "slope Flat" parenthetical in the flat-slope Neutral case, since asserting it unqualified would contradict the hedge in the same sentence', () => {
      const message = tideHelp.interpretValue('NEUTRAL', 'flat')
      expect(message).not.toMatch(/weekly MACD-H slope Flat/)
      expect(message.startsWith('Currently Neutral --')).toBe(true)
    })

    it('explains a Neutral tide with a rising/falling slope as a weekly EMA(13)/MACD-Histogram direction disagreement (weekly Impulse Blue)', () => {
      const message = tideHelp.interpretValue('NEUTRAL', 'rising')
      expect(message).toMatch(/no directional Triple Screen setup/)
      expect(message).toMatch(
        /weekly EMA\(13\) and weekly MACD-Histogram aren.t moving in the same direction, so the weekly Impulse System reads Blue/,
      )
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

  describe('seasonHelp.interpretValue', () => {
    it('frames Spring as the best long entry despite feeling emotionally wrong', () => {
      const message = seasonHelp.interpretValue('Spring')
      expect(message).toMatch(/^Currently Spring/)
      expect(message).toMatch(/best risk\/reward entry for a long/)
      expect(message).toMatch(/hardest to take emotionally/)
    })

    it('frames Autumn as the best short entry despite feeling emotionally wrong', () => {
      const message = seasonHelp.interpretValue('Autumn')
      expect(message).toMatch(/^Currently Autumn/)
      expect(message).toMatch(/best risk\/reward entry for a short/)
      expect(message).toMatch(/hardest to take emotionally/)
    })

    it('frames Summer as a worse-value, crowd-recognized entry than Spring', () => {
      const message = seasonHelp.interpretValue('Summer')
      expect(message).toMatch(/^Currently Summer/)
      expect(message).toMatch(/crowd-recognized uptrend/)
      expect(message).toMatch(/worse-value entry than Spring/)
    })

    it('frames Winter as a worse-value, crowd-recognized entry than Autumn', () => {
      const message = seasonHelp.interpretValue('Winter')
      expect(message).toMatch(/^Currently Winter/)
      expect(message).toMatch(/crowd-recognized downtrend/)
      expect(message).toMatch(/worse-value entry than Autumn/)
    })

    it('reports unavailability for a null/undefined season (warm-up)', () => {
      expect(seasonHelp.interpretValue(null)).toMatch(/unavailable/)
      expect(seasonHelp.interpretValue(undefined)).toMatch(/unavailable/)
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

  describe('rsiHelp.interpretValue', () => {
    it('handles a missing value without throwing', () => {
      expect(() => rsiHelp.interpretValue(null, null)).not.toThrow()
      expect(rsiHelp.interpretValue(undefined, undefined)).toMatch(/unavailable/)
      expect(rsiHelp.interpretValue(null, 55.0)).toMatch(/unavailable/)
    })

    it('reads below 30 as oversold', () => {
      expect(rsiHelp.interpretValue(24.3, 20.0)).toContain('oversold (below 30)')
    })

    it('reads exactly 30 as not oversold (oversold is strictly below 30)', () => {
      expect(rsiHelp.interpretValue(30, 30)).toContain('neutral zone')
    })

    it('reads above 70 as overbought', () => {
      expect(rsiHelp.interpretValue(78.1, 82.0)).toContain('overbought (above 70)')
    })

    it('reads exactly 70 as not overbought (overbought is strictly above 70)', () => {
      expect(rsiHelp.interpretValue(70, 70)).toContain('neutral zone')
    })

    it('reads between 30 and 70 as neutral', () => {
      expect(rsiHelp.interpretValue(48.2, 55.0)).toContain(
        'in the neutral zone (30-70): neither overbought nor oversold',
      )
    })

    it('omits the Stochastic comparison entirely when Stochastic %K is unavailable', () => {
      expect(rsiHelp.interpretValue(48.2, null)).toBe(
        'Currently 48.2, in the neutral zone (30-70): neither overbought nor oversold.',
      )
    })

    it('reads a close reading (within 10 points) as broadly agreeing with Stochastic', () => {
      expect(rsiHelp.interpretValue(29.5, 24.3)).toContain(
        'broadly agreeing with Stochastic %K (24.3) right now',
      )
    })

    it('reads a reading more than 10 points apart as diverging from Stochastic, naming the closing-price-only reason (RSI stronger)', () => {
      const message = rsiHelp.interpretValue(60.0, 20.0)
      expect(message).toContain('reading stronger than Stochastic %K (20.0) right now')
      expect(message).toContain('closing prices')
    })

    it('reads a reading more than 10 points apart the other direction as weaker than Stochastic', () => {
      const message = rsiHelp.interpretValue(20.0, 60.0)
      expect(message).toContain('reading weaker than Stochastic %K (60.0) right now')
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
      expect(supportResistanceZoneHelp.interpretValue([], [], 229.7)).toBe(
        'No support/resistance zones detected yet for this ticker -- needs at least 2 clustered swing-point touches spanning 14+ days.',
      )
    })

    it('reports the displayed/detected count without a nearest-zone reading when latestClose is unknown', () => {
      const zones = [buildZone()]
      expect(supportResistanceZoneHelp.interpretValue(zones, zones, undefined)).toBe(
        'Showing 1 of 1 detected zone (strongest first).',
      )
      expect(supportResistanceZoneHelp.interpretValue(zones, zones, null)).toBe(
        'Showing 1 of 1 detected zone (strongest first).',
      )
    })

    it('pluralizes "zone(s)" correctly for a single vs. multiple detected zones', () => {
      const oneZone = [buildZone()]
      const twoZones = [buildZone(), buildZone({ upper: 210, lower: 205 })]
      expect(
        supportResistanceZoneHelp.interpretValue(oneZone, oneZone, undefined),
      ).toMatch(/1 detected zone \(/)
      expect(
        supportResistanceZoneHelp.interpretValue(twoZones, twoZones, undefined),
      ).toMatch(/2 detected zones \(/)
    })

    it('identifies the zone nearest the latest close among several, by distance to its nearer edge', () => {
      const resistance = buildZone({ role: 'resistance', upper: 231.0, lower: 229.9 })
      const support = buildZone({ role: 'support', upper: 210.0, lower: 205.0 })
      const message = supportResistanceZoneHelp.interpretValue(
        [resistance, support],
        [resistance, support],
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
        [containing, nearButOutside],
        229.7,
      )
      expect(message).toMatch(/Support 228\.00-231\.00/)
    })

    it('notes when the nearest zone has flipped role after a confirmed break', () => {
      const zone = buildZone({ broken: true, break_date: '2026-08-01' })
      const message = supportResistanceZoneHelp.interpretValue([zone], [zone], 235.0)
      expect(message).toMatch(/role flipped after a confirmed break/)
    })

    it('omits the role-flipped clause for a zone that has never broken', () => {
      const zone = buildZone({ broken: false })
      const message = supportResistanceZoneHelp.interpretValue([zone], [zone], 235.0)
      expect(message).not.toMatch(/role flipped/)
    })

    it('reports the displayed count against the total detected count, not just the detected count twice, when some zones are filtered out', () => {
      // Regression test for PR #152 retry round 2: the legend must describe
      // `displayedZones` (relevance-filtered + capped), never the raw
      // `zones` list -- distinct arguments here catch a caller that
      // accidentally passes the same list twice.
      const allZones = [buildZone(), buildZone({ upper: 210, lower: 205 })]
      const displayed = [allZones[0]]
      expect(
        supportResistanceZoneHelp.interpretValue(allZones, displayed, 235.0),
      ).toMatch(/^Showing 1 of 2 detected zones/)
    })

    it("picks 'nearest' only from displayedZones, never from a zone that was filtered out of the raw list", () => {
      // The exact bug the reviewer reproduced live on AAPL/MSFT/AMD: a
      // stale/irrelevant zone (here, one far below the close) is closer to
      // `latestClose` than every zone actually displayed, but must never be
      // reported as "nearest" since it isn't drawn on the chart.
      const farAway = buildZone({ role: 'support', upper: 1.0, lower: 0.5 })
      const displayedResistance = buildZone({
        role: 'resistance',
        upper: 350.0,
        lower: 340.0,
      })
      const message = supportResistanceZoneHelp.interpretValue(
        [farAway, displayedResistance],
        [displayedResistance],
        300.0,
      )
      expect(message).toMatch(/Resistance 340\.00-350\.00/)
      expect(message).not.toMatch(/0\.50-1\.00/)
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

    it('never describes a false breakout belonging to a zone excluded from displayedZones', () => {
      // Regression test for PR #152 retry round 2: the caller must pass
      // the relevance-filtered/capped `displayedZones` list here, not the
      // raw API response -- a zone with a false breakout that isn't in
      // that list must not be described, even if it's the only breakout
      // that exists at all.
      const excludedWithBreakout = buildZone({
        role: 'support',
        upper: 1.0,
        lower: 0.5,
        false_breakout: {
          direction: 'down',
          breakout_date: '2026-08-20',
          reentry_date: '2026-09-02',
          extreme_price: 0.4,
        },
      })
      // Simulates the caller passing only the displayed zones -- the
      // excluded zone above isn't among them.
      const displayedZones = [
        buildZone({ role: 'resistance', upper: 350.0, lower: 340.0 }),
      ]
      const message = falseBreakoutHelp.interpretValue(displayedZones)
      expect(message).toBe('No false breakouts detected among these zones right now.')
      expect(message).not.toMatch(
        excludedWithBreakout.false_breakout!.extreme_price.toFixed(2),
      )
    })

    it('omits the out-of-range clause when inVisibleRange is true (or omitted, the default)', () => {
      const zone = buildZone({
        false_breakout: {
          direction: 'up',
          breakout_date: '2026-08-20',
          reentry_date: '2026-09-02',
          extreme_price: 238.5,
        },
      })
      expect(falseBreakoutHelp.interpretValue([zone])).not.toContain(
        "isn't marked on the chart right now",
      )
      expect(falseBreakoutHelp.interpretValue([zone], true)).not.toContain(
        "isn't marked on the chart right now",
      )
    })

    it('appends an out-of-range clause naming the reentry_date when inVisibleRange is false, mirroring divergenceHelp/kangarooTailHelp', () => {
      const zone = buildZone({
        role: 'resistance',
        upper: 236.9,
        lower: 233.4,
        false_breakout: {
          direction: 'up',
          breakout_date: '2025-01-01',
          reentry_date: '2025-01-15',
          extreme_price: 238.5,
        },
      })
      const message = falseBreakoutHelp.interpretValue([zone], false)
      // Still names the real episode in full...
      expect(message).toContain(
        'resistance zone 233.40-236.90 broke above it on 2025-01-01',
      )
      expect(message).toContain('238.50')
      // ...plus the out-of-range explanation.
      expect(message).toContain("isn't marked on the chart right now")
      expect(message).toContain('2025-01-15')
    })
  })

  describe('divergenceHelp.interpretValue', () => {
    function buildDivergence(overrides: Partial<DivergenceOut> = {}): DivergenceOut {
      return {
        indicator: 'macd_histogram',
        kind: 'bullish',
        first_extreme_date: '2026-08-03',
        first_extreme_price: 210.5,
        first_extreme_indicator_value: -6.0,
        second_extreme_date: '2026-08-31',
        second_extreme_price: 205.2,
        second_extreme_indicator_value: -1.5,
        bars_apart: 20,
        centerline_crossed: true,
        beyond_reference_line: null,
        aborted: false,
        ...overrides,
      }
    }

    it('reports no divergence when null', () => {
      expect(divergenceHelp.interpretValue(null)).toBe(
        'No currently qualifying divergence detected for this ticker.',
      )
    })

    it('names the actual two dates/values compared for a bullish MACD-Histogram divergence, citing the centerline-crossing requirement', () => {
      const message = divergenceHelp.interpretValue(buildDivergence())
      expect(message).toContain('Bullish MACD-Histogram divergence')
      expect(message).toContain('2026-08-03 (price 210.50, MACD-Histogram -6.00)')
      expect(message).toContain('2026-08-31 (price 205.20, MACD-Histogram -1.50)')
      expect(message).toContain('crossed back through its own zero centerline')
      expect(message).toContain('20 trading days apart')
      expect(message).toContain('a potential buy setup')
    })

    it('names a bearish Stochastic divergence beyond the reference line as its textbook-strongest form', () => {
      const message = divergenceHelp.interpretValue(
        buildDivergence({
          indicator: 'stochastic',
          kind: 'bearish',
          centerline_crossed: null,
          beyond_reference_line: true,
        }),
      )
      expect(message).toContain('Bearish Stochastic %K divergence')
      expect(message).toContain('swing highs')
      expect(message).toContain('textbook-strongest form')
      expect(message).toContain('a potential sell setup')
    })

    it('names an RSI divergence NOT beyond the reference line as still qualifying but not its strongest form', () => {
      const message = divergenceHelp.interpretValue(
        buildDivergence({
          indicator: 'rsi',
          centerline_crossed: null,
          beyond_reference_line: false,
        }),
      )
      expect(message).toContain('RSI divergence')
      expect(message).toContain('no centerline requirement')
      expect(message).toContain('didn’t reach beyond the 30/70 reference line')
    })

    it('appends the Hound of the Baskervilles callout when aborted', () => {
      const message = divergenceHelp.interpretValue(buildDivergence({ aborted: true }))
      expect(message).toContain('Hound of the Baskervilles')
      expect(message).toContain('strong continuation signal the other way')
    })

    it('omits the Hound of the Baskervilles callout when not aborted', () => {
      const message = divergenceHelp.interpretValue(buildDivergence({ aborted: false }))
      expect(message).not.toContain('Hound of the Baskervilles')
    })

    it('omits the out-of-range clause when inVisibleRange is true (or omitted, the default)', () => {
      expect(divergenceHelp.interpretValue(buildDivergence())).not.toContain(
        'isn’t drawn on the chart right now',
      )
      expect(divergenceHelp.interpretValue(buildDivergence(), true)).not.toContain(
        'isn’t drawn on the chart right now',
      )
    })

    it('appends an out-of-range clause naming the divergence’s own dates when inVisibleRange is false', () => {
      const message = divergenceHelp.interpretValue(buildDivergence(), false)
      // Still names the real divergence...
      expect(message).toContain('Bullish MACD-Histogram divergence')
      // ...plus the out-of-range explanation.
      expect(message).toContain('isn’t drawn on the chart right now')
      expect(message).toContain('2026-08-03 to 2026-08-31')
    })
  })

  describe('kangarooTailHelp.interpretValue', () => {
    function buildTail(overrides: Partial<KangarooTailOut> = {}): KangarooTailOut {
      return {
        direction: 'up',
        tail_date: '2026-08-15',
        confirmed_date: '2026-08-16',
        high: 150.0,
        low: 137.66,
        range_multiple: 2.8,
        suggested_stop: 143.83,
        ...overrides,
      }
    }

    function buildTailBar(
      overrides: Partial<HistoryResponse['bars'][number]> = {},
    ): HistoryResponse['bars'][number] {
      return {
        date: '2026-08-15',
        open: 145.2,
        high: 150.0,
        low: 137.66,
        close: 139.1,
        volume: 5_000_000,
        ...overrides,
      }
    }

    it('reports no tail when null', () => {
      expect(kangarooTailHelp.interpretValue(null, undefined)).toBe(
        'No currently confirmed Kangaroo Tail pattern detected for this ticker.',
      )
    })

    it("names the tail's own range vs. the recent average, its open/close vs. the extreme, the confirming bar, and the suggested stop, all in this ticker's own actual numbers", () => {
      const message = kangarooTailHelp.interpretValue(buildTail(), buildTailBar())
      expect(message).toContain('Bearish (upward-pointing) Kangaroo Tail')
      expect(message).toContain('On 2026-08-15')
      expect(message).toContain('12.34')
      expect(message).toContain('high 150.00, low 137.66')
      expect(message).toContain('2.8x')
      expect(message).toContain('~4.41 average range')
      expect(message).toContain('open (145.20)')
      expect(message).toContain('close (139.10)')
      expect(message).toContain('nearest the low')
      expect(message).toContain('not the new high')
      expect(message).toContain('Confirmed on 2026-08-16')
      expect(message).toContain("continued below this bar's close")
      expect(message).toContain('Suggested stop: 143.83')
      expect(message).toContain('tip (150.00, too wide)')
      expect(message).toContain('base (137.66, too tight)')
    })

    it('describes a downward (bullish) tail with the mirrored open/close/tip/base language', () => {
      const tail = buildTail({
        direction: 'down',
        high: 112.0,
        low: 99.5,
        suggested_stop: 105.75,
      })
      const tailBar = buildTailBar({ high: 112.0, low: 99.5, open: 104.0, close: 108.9 })
      const message = kangarooTailHelp.interpretValue(tail, tailBar)
      expect(message).toContain('Bullish (downward-pointing) Kangaroo Tail')
      expect(message).toContain('nearest the high')
      expect(message).toContain('not the new low')
      expect(message).toContain("continued above this bar's close")
      expect(message).toContain('tip (99.50, too wide)')
      expect(message).toContain('base (112.00, too tight)')
    })

    it('still describes the pattern from high/low/range_multiple/suggested_stop alone when the tail bar itself is unavailable (e.g. its date falls outside the currently fetched history)', () => {
      const message = kangarooTailHelp.interpretValue(buildTail(), undefined)
      expect(message).toContain('Bearish (upward-pointing) Kangaroo Tail')
      expect(message).toContain('12.34')
      expect(message).toContain('Suggested stop: 143.83')
      expect(message).not.toContain('open (')
      expect(message).not.toContain('close (')
    })

    it('omits the out-of-range clause when inVisibleRange is true (or omitted, the default)', () => {
      expect(kangarooTailHelp.interpretValue(buildTail(), buildTailBar())).not.toContain(
        "isn't marked on the chart right now",
      )
      expect(
        kangarooTailHelp.interpretValue(buildTail(), buildTailBar(), true),
      ).not.toContain("isn't marked on the chart right now")
    })

    it("appends an out-of-range clause naming the tail's own date when inVisibleRange is false", () => {
      const message = kangarooTailHelp.interpretValue(buildTail(), buildTailBar(), false)
      expect(message).toContain('Bearish (upward-pointing) Kangaroo Tail')
      expect(message).toContain("isn't marked on the chart right now")
      expect(message).toContain('2026-08-15 falls outside the currently selected range')
    })
  })

  describe('countTideTrends / tideRegionHelp.interpretValue (frontend-tide-region-chart-shading)', () => {
    function buildPoint(
      date: string,
      trend: IndicatorHistoryPoint['tide']['trend'],
    ): IndicatorHistoryPoint {
      return {
        date,
        tide: { trend, weekly_macd_histogram_slope: 'flat' },
        ema_13: 100,
        ema_26: 98,
        macd_histogram: 0.5,
        bull_power: 1,
        bear_power: -1,
        obv: 5000.0,
        accumulation_distribution: 1200.0,
        trend_strength: { atr: 3.8, plus_di: 26.0, minus_di: 18.5, adx: 20.0 },
        signal: 'HOLD',
        confidence: 0,
        confidence_band: 'Low',
      }
    }

    it('tallies each trend value independently', () => {
      const points = [
        buildPoint('2026-08-28', 'BULLISH'),
        buildPoint('2026-08-31', 'BULLISH'),
        buildPoint('2026-09-01', 'NEUTRAL'),
        buildPoint('2026-09-02', 'BEARISH'),
      ]
      expect(countTideTrends(points)).toEqual({ bullish: 2, bearish: 1, neutral: 1 })
    })

    it('returns all-zero counts for an empty array', () => {
      expect(countTideTrends([])).toEqual({ bullish: 0, bearish: 0, neutral: 0 })
    })

    it('reports "unavailable" when there are no currently visible points', () => {
      expect(tideRegionHelp.interpretValue([])).toBe(
        'Currently unavailable for this ticker.',
      )
    })

    it("reports the Bullish/Bearish/Neutral percentage split and the latest (rightmost) bar's trend", () => {
      const points = [
        buildPoint('2026-08-28', 'BULLISH'),
        buildPoint('2026-08-31', 'BULLISH'),
        buildPoint('2026-09-01', 'NEUTRAL'),
        buildPoint('2026-09-02', 'BEARISH'),
      ]
      const message = tideRegionHelp.interpretValue(points)
      expect(message).toContain('Across the 4 bars currently shown')
      expect(message).toContain('50% Bullish')
      expect(message).toContain('25% Bearish')
      expect(message).toContain('25% Neutral')
      expect(message).toContain("Today's (rightmost) background is Bearish (red)")
    })

    it('reports 100% Bullish and a Bullish (green) latest reading when every visible bar is Bullish', () => {
      const points = [
        buildPoint('2026-09-01', 'BULLISH'),
        buildPoint('2026-09-02', 'BULLISH'),
      ]
      const message = tideRegionHelp.interpretValue(points)
      expect(message).toContain('100% Bullish, 0% Bearish, 0% Neutral')
      expect(message).toContain("Today's (rightmost) background is Bullish (green)")
    })
  })

  describe('obvHelp / accumulationDistributionHelp (frontend-volume-indicators-chart)', () => {
    function buildPoint(
      date: string,
      obv: number,
      accumulationDistribution: number,
    ): IndicatorHistoryPoint {
      return {
        date,
        tide: { trend: 'NEUTRAL', weekly_macd_histogram_slope: 'flat' },
        ema_13: 100,
        ema_26: 98,
        macd_histogram: 0.5,
        bull_power: 1,
        bear_power: -1,
        obv,
        accumulation_distribution: accumulationDistribution,
        trend_strength: { atr: 3.8, plus_di: 26.0, minus_di: 18.5, adx: 20.0 },
        signal: 'HOLD',
        confidence: 0,
        confidence_band: 'Low',
      }
    }

    it("explains what OBV is and Elder's two divergence/trading-range reading styles", () => {
      expect(obvHelp.definition).toMatch(/running cumulative total/)
      expect(obvHelp.elderContext).toMatch(/divergence/)
      expect(obvHelp.elderContext).toMatch(/trading-range/)
      expect(obvHelp.elderContext).toMatch(/ahead of/)
    })

    it('explains what A/D is and how it differs from OBV and Elder-Ray', () => {
      expect(accumulationDistributionHelp.definition).toMatch(/close - open/)
      expect(accumulationDistributionHelp.elderContext).toMatch(/Elder-Ray/)
    })

    it('reports "unavailable" for an empty points array', () => {
      expect(obvHelp.interpretValue([])).toBe('Currently unavailable for this ticker.')
      expect(accumulationDistributionHelp.interpretValue([])).toBe(
        'Currently unavailable for this ticker.',
      )
    })

    it("states the raw value together with the 'means nothing on its own' caveat, never the raw value alone", () => {
      const points = [
        buildPoint('2026-09-01', 5000, 1200),
        buildPoint('2026-09-02', 10500, 900),
      ]
      const message = obvHelp.interpretValue(points)
      expect(message).toContain('Currently 10500 as of 2026-09-02')
      expect(message).toContain('means nothing on its own')
    })

    it('describes a rising OBV currently at its own window high', () => {
      const points = [
        buildPoint('2026-09-01', 5000, 1200),
        buildPoint('2026-09-02', 10500, 900),
      ]
      const message = obvHelp.interpretValue(points)
      expect(message).toContain('OBV has risen over the 2 bars currently shown')
      expect(message).toContain(
        'It is currently at its own highest point over this window.',
      )
    })

    it('describes a falling A/D currently at its own window low', () => {
      const points = [
        buildPoint('2026-09-01', 5000, 1200),
        buildPoint('2026-09-02', 10500, 900),
      ]
      const message = accumulationDistributionHelp.interpretValue(points)
      expect(message).toContain('A/D has fallen over the 2 bars currently shown')
      expect(message).toContain(
        'It is currently at its own lowest point over this window.',
      )
    })

    it('describes a flat series and names the window high/low when the latest bar is neither', () => {
      const points = [
        buildPoint('2026-08-30', 5000, 1200),
        buildPoint('2026-08-31', 8000, 1200),
        buildPoint('2026-09-01', 3000, 1200),
        buildPoint('2026-09-02', 5000, 1200),
      ]
      const message = obvHelp.interpretValue(points)
      expect(message).toContain('OBV has stayed flat over the 4 bars currently shown')
      expect(message).toContain(
        'its own high was 8000 (2026-08-31) and low was 3000 (2026-09-01)',
      )
    })

    it('handles a single-bar window without a plural mismatch', () => {
      const points = [buildPoint('2026-09-02', 5000, 1200)]
      const message = obvHelp.interpretValue(points)
      expect(message).toContain('OBV has stayed flat over the 1 bar currently shown')
      expect(message).toContain(
        'It is currently at its own highest point over this window.',
      )
    })
  })

  describe('directionalSystemHelp / adxHelp / atrHelp (frontend-trend-strength-chart)', () => {
    function buildPoint(
      date: string,
      trendStrength: Partial<{
        atr: number | null
        plus_di: number | null
        minus_di: number | null
        adx: number | null
      }> = {},
      emaOverride?: number,
    ): IndicatorHistoryPoint {
      return {
        date,
        tide: { trend: 'NEUTRAL', weekly_macd_histogram_slope: 'flat' },
        ema_13: emaOverride ?? 100,
        ema_26: 98,
        macd_histogram: 0.5,
        bull_power: 1,
        bear_power: -1,
        obv: 5000.0,
        accumulation_distribution: 1200.0,
        trend_strength: {
          atr: 3.8,
          plus_di: 26.0,
          minus_di: 18.5,
          adx: 20.0,
          ...trendStrength,
        },
        signal: 'HOLD',
        confidence: 0,
        confidence_band: 'Low',
      }
    }

    it('explains +DI/-DI, ADX, and ATR, each citing docs/Analyse.md/docs/ideas.md', () => {
      expect(directionalSystemHelp.definition).toMatch(/extending beyond the prior day/)
      expect(directionalSystemHelp.elderContext).toMatch(/trade long only/)
      expect(adxHelp.definition).toMatch(/DX = 100/)
      expect(adxHelp.elderContext).toMatch(/rings a bell/)
      expect(atrHelp.definition).toMatch(/13-day simple average of True Range/)
      expect(atrHelp.elderContext).toMatch(/at least 1 ATR/)
    })

    it('reports +DI/-DI as unavailable while either is still warming up', () => {
      expect(directionalSystemHelp.interpretValue(undefined, undefined)).toBe(
        'Currently unavailable for this ticker -- both need a 13-day warm-up window over True Range/+DM/-DM.',
      )
      expect(directionalSystemHelp.interpretValue(26.0, null)).toBe(
        'Currently unavailable for this ticker -- both need a 13-day warm-up window over True Range/+DM/-DM.',
      )
    })

    it('reports a tie as neither direction dominating', () => {
      expect(directionalSystemHelp.interpretValue(20.0, 20.0)).toBe(
        'Currently tied at 20.0 -- neither direction currently dominates.',
      )
    })

    it('names +DI as leading (favoring long setups) when it is higher', () => {
      const message = directionalSystemHelp.interpretValue(28.5, 15.3)
      expect(message).toContain('+DI leads')
      expect(message).toContain('long setups only')
    })

    it('names -DI as leading (favoring short setups) when it is higher', () => {
      const message = directionalSystemHelp.interpretValue(15.3, 28.5)
      expect(message).toContain('-DI leads')
      expect(message).toContain('short setups only')
    })

    it('reports ADX as unavailable for an empty points array', () => {
      expect(adxHelp.interpretValue([])).toBe(
        "Currently unavailable for this ticker -- ADX needs roughly twice +DI/-DI/ATR's own warm-up window (a further 13-bar smoothing of DX on top of theirs).",
      )
    })

    it('describes ADX with no prior bar to compare against for a single-point window', () => {
      const points = [buildPoint('2026-09-02', { adx: 20.0 })]
      const message = adxHelp.interpretValue(points)
      expect(message).toContain('with no prior bar shown to compare against')
    })

    it('describes ADX sitting at its own recent low as a lull', () => {
      const points = [
        buildPoint('2026-09-01', { adx: 25.0 }),
        buildPoint('2026-09-02', { adx: 20.0 }),
      ]
      const message = adxHelp.interpretValue(points)
      expect(message).toContain('falling from the prior bar')
      expect(message).toContain('sitting at its own low point')
    })

    it("describes ADX risen 4+ points off its own recent low as ringing Elder's bell", () => {
      const points = [
        buildPoint('2026-09-01', { adx: 20.0 }),
        buildPoint('2026-09-02', { adx: 24.0 }),
      ]
      const message = adxHelp.interpretValue(points)
      expect(message).toContain('rising from the prior bar')
      expect(message).toContain('risen 4.0 points')
      expect(message).toContain('at or beyond Elder')
    })

    it("describes ADX risen less than 4 points off its own recent low as short of Elder's bell", () => {
      const points = [
        buildPoint('2026-09-01', { adx: 20.0 }),
        buildPoint('2026-09-02', { adx: 22.0 }),
      ]
      const message = adxHelp.interpretValue(points)
      expect(message).toContain('risen 2.0 points')
      expect(message).toContain("short of Elder's own 4-point")
    })

    it('excludes still-warming-up ADX values when finding the recent low', () => {
      const points = [
        buildPoint('2026-09-01', { adx: null }),
        buildPoint('2026-09-02', { adx: 20.0 }),
        buildPoint('2026-09-03', { adx: 20.0 }),
      ]
      const message = adxHelp.interpretValue(points)
      expect(message).toContain('flat versus the prior bar')
    })

    it('reports ATR as unavailable for an empty points array', () => {
      expect(atrHelp.interpretValue([])).toBe(
        'Currently unavailable for this ticker -- ATR needs 13 prior True Range values (itself needing a prior close) before it warms up.',
      )
    })

    it('states the current ATR value as a percentage of EMA(13) and the 1-ATR stop-distance rule', () => {
      const points = [buildPoint('2026-09-02', { atr: 4.2 }, 210.0)]
      const message = atrHelp.interpretValue(points)
      expect(message).toContain('Currently 4.20 as of 2026-09-02')
      expect(message).toContain('2.0% of')
      expect(message).toContain('closer than 1 ATR (4.20) from entry')
    })

    it('omits a point with a still-warming-up ATR value from the series', () => {
      const points = [
        buildPoint('2026-09-01', { atr: null }, 200.0),
        buildPoint('2026-09-02', { atr: 4.2 }, 210.0),
      ]
      const message = atrHelp.interpretValue(points)
      expect(message).toContain('Currently 4.20 as of 2026-09-02')
    })
  })

  describe('earningsDateHelp.interpretValue (frontend-fundamental-data-panel)', () => {
    it('reports no upcoming earnings date on record', () => {
      expect(earningsDateHelp.interpretValue(null, false)).toBe(
        'No upcoming earnings date currently on record for this ticker.',
      )
    })

    it('flags a date within the 14-day warning window with Elder’s own advice', () => {
      const message = earningsDateHelp.interpretValue('2026-09-25', true)
      expect(message).toContain('2026-09-25 -- within the next 14 days')
      expect(message).toContain('avoid opening a fresh position')
      expect(message).toContain(
        'no real protection against an overnight earnings-surprise gap',
      )
    })

    it('describes a date outside the warning window as such', () => {
      const message = earningsDateHelp.interpretValue('2026-12-01', false)
      expect(message).toBe(
        "2026-12-01 -- more than 14 days out, outside this app's 14-day earnings warning window.",
      )
    })
  })

  describe('exDividendDateHelp.interpretValue', () => {
    it('reports no ex-dividend date currently scheduled', () => {
      expect(exDividendDateHelp.interpretValue(null)).toBe(
        'No ex-dividend date currently scheduled for this ticker.',
      )
    })

    it('states the scheduled date', () => {
      expect(exDividendDateHelp.interpretValue('2026-11-15')).toBe('2026-11-15.')
    })
  })

  describe('shortInterestHelp.interpretValue', () => {
    it('reports unavailable when every field is null', () => {
      expect(shortInterestHelp.interpretValue(null, null, null, null)).toBe(
        'Currently unavailable for this ticker -- not reported by this data source.',
      )
    })

    it('flags an elevated (>=10%) short-percent-of-float as meaningful squeeze fuel for a BUY', () => {
      const message = shortInterestHelp.interpretValue(5_000_000, 4.2, 0.15, 33_000_000)
      expect(message).toContain('5,000,000 shares short')
      expect(message).toContain('15.0% of float')
      expect(message).toContain('4.2 days to cover')
      expect(message).toContain('float of 33,000,000 shares')
      expect(message).toContain('elevated short-percent-of-float (>=10%)')
      expect(message).toContain(
        'meaningful squeeze fuel if this ticker rallies on a fresh BUY setup',
      )
    })

    it('describes a modest (<10%) short-percent-of-float as limited squeeze fuel', () => {
      const message = shortInterestHelp.interpretValue(1_000_000, 2.0, 0.045, 22_000_000)
      expect(message).toContain('modest short-percent-of-float (<10%)')
      expect(message).toContain('limited extra squeeze fuel')
    })

    it('omits the squeeze note entirely when short_percent_of_float alone is unavailable', () => {
      const message = shortInterestHelp.interpretValue(1_000_000, 2.0, null, 22_000_000)
      expect(message).toBe(
        'Currently 1,000,000 shares short, 2.0 days to cover, float of 22,000,000 shares.',
      )
    })

    it('reports only the fields yfinance actually returned when shares_short/short_ratio/float_shares are individually missing', () => {
      // shares_short null, short_ratio null, float_shares null -- only
      // short_percent_of_float reported (a real yfinance partial-data case,
      // Elder ch. 37: "yfinance's own data can be incomplete for smaller
      // tickers").
      const message = shortInterestHelp.interpretValue(null, null, 0.08, null)
      expect(message).toBe(
        'Currently 8.0% of float. A modest short-percent-of-float (<10%) -- limited extra squeeze fuel either way.',
      )
    })
  })

  describe('insiderTransactionsHelp.interpretValue', () => {
    it('reports no insider transactions for an empty list', () => {
      expect(insiderTransactionsHelp.interpretValue([])).toBe(
        'No insider transactions currently reported for this ticker.',
      )
    })

    it("notes a single filing falls short of Elder's 3-filing cluster threshold", () => {
      const message = insiderTransactionsHelp.interpretValue([
        {
          insider: 'Cook Timothy D',
          position: 'Chief Executive Officer',
          transaction_text: 'Sale at price 220.00 - 225.00 per share.',
          shares: 50_000,
          value: 11_000_000,
          start_date: '2026-08-01',
          ownership: 'D',
        },
      ])
      expect(message).toContain('1 filing shown, most recent filing dated 2026-08-01')
      expect(message).toContain('on its own, not usually treated as a meaningful signal')
    })

    it('notes 3+ filings without auto-classifying them as a confirmed cluster', () => {
      const transaction = {
        insider: 'A',
        position: null,
        transaction_text: 'Sale.',
        shares: null,
        value: null,
        start_date: null,
        ownership: null,
      }
      const message = insiderTransactionsHelp.interpretValue([
        transaction,
        transaction,
        transaction,
      ])
      expect(message).toContain('3 filings shown')
      expect(message).toContain('Three or more filings are shown')
      expect(message).not.toContain('most recent filing dated')
    })
  })

  describe('insiderClustersHelp.interpretValue', () => {
    function buildCluster(overrides: Partial<InsiderClusterOut> = {}): InsiderClusterOut {
      return {
        direction: 'buy',
        insiders: ['Alice Smith', 'Bob Jones', 'Carol White'],
        window_start_date: '2026-07-01',
        window_end_date: '2026-07-20',
        transaction_count: 3,
        total_shares: 60_000,
        total_value: 3_000_000,
        ...overrides,
      }
    }

    it('reports no qualifying cluster for an empty list', () => {
      expect(insiderClustersHelp.interpretValue([])).toBe(
        "No qualifying cluster (3+ distinct insiders trading the same direction within a rolling 30-day window) currently detected among this ticker's filings.",
      )
    })

    it('describes a single buy cluster', () => {
      const message = insiderClustersHelp.interpretValue([buildCluster()])
      expect(message).toContain('1 cluster currently detected')
      expect(message).toContain(
        'Buy cluster: 3 distinct insiders (3 filings) between 2026-07-01 and 2026-07-20',
      )
    })

    it('describes a single sell cluster', () => {
      const message = insiderClustersHelp.interpretValue([
        buildCluster({ direction: 'sell', transaction_count: 5 }),
      ])
      expect(message).toContain('Sell cluster: 3 distinct insiders (5 filings)')
    })

    it('lists multiple clusters most-recent-window-first, exercising both sort-comparator directions', () => {
      const message = insiderClustersHelp.interpretValue([
        buildCluster({
          direction: 'sell',
          window_start_date: '2026-06-01',
          window_end_date: '2026-06-15',
        }),
        buildCluster({
          direction: 'buy',
          window_start_date: '2026-04-01',
          window_end_date: '2026-04-15',
        }),
        buildCluster({
          direction: 'sell',
          window_start_date: '2026-08-01',
          window_end_date: '2026-08-20',
        }),
      ])
      expect(message).toContain('3 clusters currently detected')
      const augIndex = message.indexOf('2026-08-20')
      const junIndex = message.indexOf('2026-06-15')
      const aprIndex = message.indexOf('2026-04-15')
      expect(augIndex).toBeGreaterThanOrEqual(0)
      expect(augIndex).toBeLessThan(junIndex)
      expect(junIndex).toBeLessThan(aprIndex)
    })
  })

  describe('fundamentalDataUnavailableHelp.interpretValue', () => {
    it("explains the fallback-provider-active state distinctly from 'checked, nothing found'", () => {
      const message = fundamentalDataUnavailableHelp.interpretValue()
      expect(message).toContain('fallback (Stooq) provider is active')
      expect(message).toContain('Not the same as "checked, nothing found"')
    })
  })
})
