import { describe, expect, it } from 'vitest'
import { buyGradeHelp, sellGradeHelp, tradeGradeHelp } from './metricHelpContent'

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
})
