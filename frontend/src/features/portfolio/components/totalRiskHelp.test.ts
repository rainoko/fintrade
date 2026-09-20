import { describe, expect, it } from 'vitest'
import { totalRiskHelp } from './totalRiskHelp'

/**
 * Unit tests for totalRiskHelp's own arithmetic, matching the sibling
 * metricHelpContent.test.ts's pattern of hand-checking `interpretValue`-
 * style output against worked examples
 * (docs/tasks/backend-trade-history-table-followups-followups.json). Locks
 * in the open-vs-realized breakdown so a future change that flips the
 * subtraction order, swaps which field is passed as `totalOpenRiskPct` vs.
 * `realizedLossesThisMonthPct`, or otherwise breaks the arithmetic fails a
 * test instead of passing CI silently -- coverage tooling previously
 * reported this file at 100% purely because the function runs
 * unconditionally on render, not because any test asserted its output.
 */
describe('totalRiskHelp', () => {
  it('computes the open-position-only share as the combined total minus realized losses, hand-checked against the PR #166 review\'s live values', () => {
    // Manually verified during PR #166's review against a real
    // /api/portfolio/risk response: 1.93% open + 691.79% realized =
    // 693.72% total.
    const content = totalRiskHelp(693.72, 691.79)

    expect(content.valueInterpretation).toBe(
      '1.93% from open positions + 691.79% from this month\'s realized losses = 693.72% total.',
    )
  })

  it('reports 0.00% open-position risk when the combined total is entirely realized losses', () => {
    const content = totalRiskHelp(4.5, 4.5)

    expect(content.valueInterpretation).toBe(
      '0.00% from open positions + 4.50% from this month\'s realized losses = 4.50% total.',
    )
  })

  it('reports 0.00% realized losses when the combined total is entirely open-position risk', () => {
    const content = totalRiskHelp(2.1, 0)

    expect(content.valueInterpretation).toBe(
      '2.10% from open positions + 0.00% from this month\'s realized losses = 2.10% total.',
    )
  })

  it('carries the fixed label, definition, and Elder context through unchanged for any input', () => {
    const content = totalRiskHelp(1, 0.5)

    expect(content.metricLabel).toBe('Total Risk (Open + Realized)')
    expect(content.definition).toMatch(/6% Rule/)
    expect(content.elderContext).toMatch(/6% of\s+equity for the current month/)
  })
})
