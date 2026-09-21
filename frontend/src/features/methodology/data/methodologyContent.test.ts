import { describe, expect, it } from 'vitest'
import { METHODOLOGY_SECTIONS, STATUS_META } from './methodologyContent'

describe('methodologyContent', () => {
  it('has at least one section', () => {
    expect(METHODOLOGY_SECTIONS.length).toBeGreaterThan(0)
  })

  it('has a unique id for every section', () => {
    const ids = METHODOLOGY_SECTIONS.map((section) => section.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('has a unique id for every entry across all sections', () => {
    const ids = METHODOLOGY_SECTIONS.flatMap((section) => section.entries.map((entry) => entry.id))
    expect(ids.length).toBeGreaterThan(0)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('gives every entry a non-empty name, citation, summary, elderContext, and appBehavior', () => {
    for (const section of METHODOLOGY_SECTIONS) {
      for (const entry of section.entries) {
        expect(entry.name.length).toBeGreaterThan(0)
        expect(entry.citation.length).toBeGreaterThan(0)
        expect(entry.summary.length).toBeGreaterThan(0)
        expect(entry.elderContext.length).toBeGreaterThan(0)
        expect(entry.appBehavior.length).toBeGreaterThan(0)
        expect(STATUS_META[entry.appStatus]).toBeDefined()
      }
    }
  })

  it('includes every core Triple Screen technique named in the task description', () => {
    const allNames = METHODOLOGY_SECTIONS.flatMap((section) =>
      section.entries.map((entry) => entry.name.toLowerCase()),
    ).join(' | ')

    for (const expected of [
      'tide',
      'force index',
      'stochastic',
      'elder-ray',
      'impulse',
      '2% rule',
      '6% rule',
    ]) {
      expect(allNames).toContain(expected)
    }
  })

  it('includes every "considered/available-but-not-load-bearing" signal named in the task description', () => {
    const allNames = METHODOLOGY_SECTIONS.flatMap((section) =>
      section.entries.map((entry) => entry.name.toLowerCase()),
    ).join(' | ')

    for (const expected of [
      'divergence',
      'support/resistance',
      'directional system',
      'rsi',
      'on-balance volume',
      'kangaroo tail',
      'indicator seasons',
      'channel',
      'ibkr',
    ]) {
      expect(allNames).toContain(expected)
    }
  })

  it('has a description for every status in STATUS_META', () => {
    for (const status of Object.keys(STATUS_META) as Array<keyof typeof STATUS_META>) {
      expect(STATUS_META[status].label.length).toBeGreaterThan(0)
      expect(STATUS_META[status].description.length).toBeGreaterThan(0)
    }
  })

  describe('profit-target entry summary', () => {
    // Content-specific regression test (unlike every other assertion in this file,
    // which only checks structural invariants) -- this exact string was the 6th
    // instance of the "stale daily-channel copy" bug found during PR #222's
    // (backend-profit-target-weekly-channel) final review round: it read "that
    // day's Autoenvelope/channel height" after suggest_profit_target's channel
    // candidate moved to the WEEKLY chart (ch. 39 p.161), and no test caught it
    // before manual review did. See
    // docs/tasks/backend-profit-target-weekly-channel-followups.json checklist
    // item 2 -- folded into the same repo-wide guard as
    // profitTargetHelpText.test.ts and both metricHelpContent.test.ts files via
    // scripts/check_profit_target_wording.py (run by the static-verify skill),
    // plus this dedicated assertion for defense in depth at the unit-test level.
    const profitTargetEntry = METHODOLOGY_SECTIONS.flatMap((section) => section.entries).find(
      (entry) => entry.id === 'profit-target',
    )

    it('exists', () => {
      expect(profitTargetEntry).toBeDefined()
    })

    it('describes the channel/Tradebill technique as sourced from the WEEKLY chart, not "today\'s"/"that day\'s"/daily', () => {
      expect(profitTargetEntry?.summary).toMatch(/weekly chart.s Autoenvelope\/channel height/)
      expect(profitTargetEntry?.summary).not.toMatch(/today.s Autoenvelope/)
      expect(profitTargetEntry?.summary).not.toMatch(/that day.s Autoenvelope/)
    })
  })
})
