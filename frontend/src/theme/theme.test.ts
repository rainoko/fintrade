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

  it('defines a divergence-marker color distinct from the BUY/SELL signal colors (frontend-divergence-markers)', () => {
    expect(theme.palette.divergence.main).toMatch(/^#/)
    expect(theme.palette.divergence.main).not.toBe(theme.palette.signal.buy)
    expect(theme.palette.divergence.main).not.toBe(theme.palette.signal.sell)
  })

  it('defines four distinct Indicator Season colors, none of which reuse a BUY/SELL/HOLD signal color (frontend-indicator-seasons-badge)', () => {
    const { spring, summer, autumn, winter } = theme.palette.season
    const seasonColors = [spring, summer, autumn, winter]
    seasonColors.forEach((color) => expect(color).toMatch(/^#/))
    expect(new Set(seasonColors).size).toBe(4)

    const { buy, sell, hold } = theme.palette.signal
    seasonColors.forEach((color) => {
      expect(color).not.toBe(buy)
      expect(color).not.toBe(sell)
      expect(color).not.toBe(hold)
    })
  })
})
