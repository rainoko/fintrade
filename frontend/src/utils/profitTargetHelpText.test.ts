import { describe, expect, it } from 'vitest'
import { PROFIT_TARGET_DEFINITION, PROFIT_TARGET_ELDER_CONTEXT_SUFFIX } from './profitTargetHelpText'

describe('profitTargetHelpText', () => {
  describe('PROFIT_TARGET_DEFINITION', () => {
    it('describes the channel/Tradebill technique as sourced from the WEEKLY chart, not "today\'s"/daily (regression test: suggest_profit_target moved its channel computation to weekly OHLCV per ch. 39 p.161, but this shared definition -- consumed by both the stocks and portfolio MetricHelp registries -- was initially left describing the old daily behavior; caught by pr-decision, not by any existing test)', () => {
      expect(PROFIT_TARGET_DEFINITION).toMatch(/weekly chart.s Autoenvelope\/channel height/)
      expect(PROFIT_TARGET_DEFINITION).not.toMatch(/today.s Autoenvelope/)
    })
  })

  // Sanity check that the shared suffix constant itself hasn't been touched
  // by this fix -- it's unrelated to the channel's timeframe (it's about the
  // 2:1 reward:risk rule), so it should still read exactly as before.
  describe('PROFIT_TARGET_ELDER_CONTEXT_SUFFIX', () => {
    it('cites the 2:1 rule and the long-only disclosure', () => {
      expect(PROFIT_TARGET_ELDER_CONTEXT_SUFFIX).toMatch(/ch\. 53/)
      expect(PROFIT_TARGET_ELDER_CONTEXT_SUFFIX).toMatch(/BUY-only/)
    })
  })
})
