import { describe, expect, it } from 'vitest'
import { isPositiveFinite } from './validation'

describe('isPositiveFinite', () => {
  it('returns true for a positive finite number', () => {
    expect(isPositiveFinite(1)).toBe(true)
    expect(isPositiveFinite(0.5)).toBe(true)
  })

  it('returns false for zero', () => {
    expect(isPositiveFinite(0)).toBe(false)
  })

  it('returns false for a negative number', () => {
    expect(isPositiveFinite(-1)).toBe(false)
  })

  it('returns false for NaN', () => {
    expect(isPositiveFinite(Number.NaN)).toBe(false)
  })

  it('returns false for Infinity', () => {
    expect(isPositiveFinite(Number.POSITIVE_INFINITY)).toBe(false)
  })
})
