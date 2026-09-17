import { describe, expect, it } from 'vitest'
import { formatNullableNumber, humanizeSnakeCase } from './format'

describe('humanizeSnakeCase', () => {
  it('returns the label map entry when the value is known', () => {
    expect(humanizeSnakeCase('stop_hit', { stop_hit: 'Stop hit' })).toBe('Stop hit')
  })

  it('falls back to underscores-to-spaces, capitalized, when no label map is given', () => {
    expect(humanizeSnakeCase('close_above_prior_high')).toBe('Close above prior high')
  })

  it('falls back the same way for a value not present in a given label map', () => {
    expect(humanizeSnakeCase('some_new_flag', { stop_hit: 'Stop hit' })).toBe('Some new flag')
  })

  it('lowercases an UPPER_SNAKE_CASE value before capitalizing only the first letter', () => {
    // Elder Triple Screen enum-like fields (tide.trend, wave.state, ...) come
    // back as UPPER_SNAKE_CASE, unlike confidence_breakdown component names
    // or exit_flags values (already lowercase) — the fallback has to
    // normalize both conventions to the same "Capitalized words" style.
    expect(humanizeSnakeCase('OVERSOLD_PULLBACK')).toBe('Oversold pullback')
  })
})

describe('formatNullableNumber', () => {
  it('formats a plain number using the given options', () => {
    expect(formatNullableNumber(24.3, { minimumFractionDigits: 1, maximumFractionDigits: 1 })).toBe(
      '24.3',
    )
  })

  it("renders '—' for null", () => {
    expect(formatNullableNumber(null)).toBe('—')
  })

  it("renders '—' for undefined", () => {
    expect(formatNullableNumber(undefined)).toBe('—')
  })

  it("renders '—' for NaN", () => {
    expect(formatNullableNumber(Number.NaN)).toBe('—')
  })

  it('formats negative numbers with grouping when no fraction-digit options are given', () => {
    expect(formatNullableNumber(-18234.5)).toBe('-18,234.5')
  })
})
