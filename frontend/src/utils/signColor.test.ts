import { describe, expect, it } from 'vitest'
import { theme } from '../theme/theme'
import { signColor } from './signColor'

describe('signColor', () => {
  it('returns the success color for a positive value', () => {
    expect(signColor(theme, 3.2)).toBe(theme.palette.success.main)
  })

  it('returns the error color for a negative value', () => {
    expect(signColor(theme, -1.5)).toBe(theme.palette.error.main)
  })

  it('returns the neutral secondary text color for zero', () => {
    expect(signColor(theme, 0)).toBe(theme.palette.text.secondary)
  })
})
