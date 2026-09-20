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
})
