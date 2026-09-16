import { describe, expect, it } from 'vitest'
import { theme } from './theme'

// Guards the semantic palette entries Frontend.md requires (BUY/SELL/HOLD
// signal colors, the portfolio risk-breach color) against being silently
// dropped or renamed — every common/ component that reads
// `theme.palette.signal.*` / `theme.palette.riskBreach.*` depends on these
// keys existing.
describe('theme', () => {
  it('defines a distinct color for each signal value', () => {
    const { buy, sell, hold } = theme.palette.signal
    expect(buy).toMatch(/^#/)
    expect(sell).toMatch(/^#/)
    expect(hold).toMatch(/^#/)
    expect(new Set([buy, sell, hold]).size).toBe(3)
  })

  it('defines a risk-breach color distinct from the sell signal color', () => {
    expect(theme.palette.riskBreach.main).toMatch(/^#/)
    expect(theme.palette.riskBreach.background).toMatch(/^#/)
    expect(theme.palette.riskBreach.main).not.toBe(theme.palette.signal.sell)
  })
})
