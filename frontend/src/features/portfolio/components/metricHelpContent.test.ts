import { describe, expect, it } from 'vitest'
import type { ProfitTargetOut } from '../../../api/stocks'
import {
  buyGradeHelp,
  profitTargetHelp,
  sellGradeHelp,
  tradeGradeHelp,
} from './metricHelpContent'

describe('portfolio metricHelpContent', () => {
  describe('buyGradeHelp.interpretValue', () => {
    it('frames the grade as how far up the day’s range the buy was, hand-checked against the book’s ADSK example', () => {
      // docs/Analyse.md §7's worked example: buy grade 97.3% -> bought
      // within 2.7% of the entry day's low.
      expect(buyGradeHelp.interpretValue(97.3)).toBe(
        'You bought at 2.7% up the entry day’s high-low range (a 97.3% buy grade) -- Elder considers a buy grade over 50% (bought in the lower half of that day’s range) "very good".',
      )
    })

    it('explains an unavailable grade instead of rendering a bare null', () => {
      expect(buyGradeHelp.interpretValue(null)).toMatch(/Not available for this trade/)
    })
  })

  describe('sellGradeHelp.interpretValue', () => {
    it('states the raw sell grade directly as "% up the range", matching the task’s own example wording', () => {
      expect(sellGradeHelp.interpretValue(35.5)).toBe(
        'You sold at 35.5% up the exit day’s high-low range -- Elder considers a sell grade over 50% "very good".',
      )
    })

    it('explains an unavailable grade instead of rendering a bare null', () => {
      expect(sellGradeHelp.interpretValue(null)).toMatch(/Not available for this trade/)
    })
  })

  describe('tradeGradeHelp.interpretValue', () => {
    it('states the channel-capture percentage, hand-checked against the book’s ADSK example', () => {
      expect(tradeGradeHelp.interpretValue(32.1)).toBe(
        'This trade captured 32.1% of the entry day’s channel height -- Elder rates roughly 30%+ capture an "A" trade, and around 10% a "C" trade.',
      )
    })

    it('explains an unavailable grade (warm-up window / insufficient history) instead of rendering a bare null', () => {
      expect(tradeGradeHelp.interpretValue(null)).toMatch(/warm-up window/)
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

    it('explains a null target as "no candidate" -- not gated on/mentioning any signal, since RiskPosition.profit_target is computed regardless of the ticker\'s current live signal (backend-profit-target-open-position)', () => {
      const text = profitTargetHelp.interpretValue(null)
      expect(text).toMatch(/neither technique.*currently produces a candidate/)
      expect(text).not.toMatch(/BUY/)
      expect(text).not.toMatch(/signal/)
    })

    it('names the channel technique and reward:risk ratio, and confirms it clears the 2:1 minimum', () => {
      const text = profitTargetHelp.interpretValue(target)
      expect(text).toContain('Currently 245.00, from the channel/Tradebill formula')
      expect(text).toContain('Reward:risk ratio 2.0:1')
      expect(text).toContain('This clears Elder’s 2:1 minimum.')
    })

    it('names the support/resistance technique and flags a ratio that fails the 2:1 minimum', () => {
      const text = profitTargetHelp.interpretValue({
        ...target,
        source: 'support_resistance',
        reward_risk_ratio: 0.9,
        meets_minimum_reward_risk: false,
      })
      expect(text).toContain('nearest detected support/resistance zone')
      expect(text).toContain('This FAILS Elder’s 2:1 minimum')
    })

    it('explains an undefined ratio (stop distance <= 0) instead of a fabricated number', () => {
      const text = profitTargetHelp.interpretValue({
        ...target,
        reward_risk_ratio: null,
        meets_minimum_reward_risk: false,
      })
      expect(text).toMatch(/reward:risk ratio is undefined right now/)
    })

    it('describes the channel technique as sourced from the WEEKLY chart, not "today\'s"/daily (regression test for the backend-profit-target-weekly-channel PR review finding: the channel moved to weekly OHLCV, but this copy was initially left describing the old daily behavior)', () => {
      const text = profitTargetHelp.interpretValue(target)
      expect(text).toContain('weekly chart’s Autoenvelope/channel height')
      expect(text).not.toMatch(/today’s Autoenvelope/)
    })

    it('describes the no-candidate warm-up window in WEEKS, not days (the channel candidate\'s warm-up is ~100 weekly bars, not ~100 daily bars)', () => {
      const text = profitTargetHelp.interpretValue(null)
      expect(text).toMatch(/~100 weeks of weekly history/)
      expect(text).not.toMatch(/100 days of history/)
    })
  })
})
