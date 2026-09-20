import { describe, expect, it } from 'vitest'
import { theme } from './theme'

// WCAG 2.x relative-luminance / contrast-ratio formulas
// (https://www.w3.org/TR/WCAG21/#contrast-minimum), used below to guard
// palette colors that get painted directly as text/icon color on a white
// card background (e.g. common/SeasonBadge's outlined Chip) rather than
// through `theme.palette.getContrastText`.
function channelToLinear(channel: number): number {
  const c = channel / 255
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

function relativeLuminance(hex: string): number {
  const value = hex.replace('#', '')
  const r = parseInt(value.slice(0, 2), 16)
  const g = parseInt(value.slice(2, 4), 16)
  const b = parseInt(value.slice(4, 6), 16)
  return 0.2126 * channelToLinear(r) + 0.7152 * channelToLinear(g) + 0.0722 * channelToLinear(b)
}

function contrastRatio(hexA: string, hexB: string): number {
  const lA = relativeLuminance(hexA)
  const lB = relativeLuminance(hexB)
  const lighter = Math.max(lA, lB)
  const darker = Math.min(lA, lB)
  return (lighter + 0.05) / (darker + 0.05)
}

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

  it('defines Indicator Season colors that clear WCAG AA 4.5:1 text contrast against a white card background (frontend-indicator-seasons-badge-followups)', () => {
    // common/SeasonBadge paints these hexes directly as its outlined Chip's
    // label text color and icon color on a white card, with no
    // `getContrastText` adjustment -- so each must independently clear the
    // WCAG AA normal-text contrast minimum against white (#ffffff), not
    // just be distinct from the signal colors (guarded above).
    const { spring, summer, autumn, winter } = theme.palette.season
    const white = '#ffffff'
    expect(contrastRatio(spring, white)).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio(summer, white)).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio(autumn, white)).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio(winter, white)).toBeGreaterThanOrEqual(4.5)
  })

  it('defines a Kangaroo Tail marker color distinct from every other marker/line color already used on PriceChart (frontend-kangaroo-tail-markers)', () => {
    const { main } = theme.palette.kangarooTail
    expect(main).toMatch(/^#/)
    expect(main).not.toBe(theme.palette.signal.buy)
    expect(main).not.toBe(theme.palette.signal.sell)
    expect(main).not.toBe(theme.palette.divergence.main)
    expect(main).not.toBe(theme.palette.warning.main)
    expect(main).not.toBe(theme.palette.info.main)
  })
})
