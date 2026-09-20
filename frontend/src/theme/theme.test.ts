import { describe, expect, it } from 'vitest'
import { theme } from './theme'

function hexToRgb(hex: string): [number, number, number] {
  const value = hex.replace('#', '')
  return [
    parseInt(value.slice(0, 2), 16),
    parseInt(value.slice(2, 4), 16),
    parseInt(value.slice(4, 6), 16),
  ]
}

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
  const [r, g, b] = hexToRgb(hex)
  return 0.2126 * channelToLinear(r) + 0.7152 * channelToLinear(g) + 0.0722 * channelToLinear(b)
}

function contrastRatio(hexA: string, hexB: string): number {
  const lA = relativeLuminance(hexA)
  const lB = relativeLuminance(hexB)
  const lighter = Math.max(lA, lB)
  const darker = Math.min(lA, lB)
  return (lighter + 0.05) / (darker + 0.05)
}

// CIE76 Lab perceptual color distance (ΔE) -- unlike the raw hex-string
// equality checks this file used to rely on (and unlike raw RGB Euclidean
// distance, which frontend-indicator-seasons-badge-followups's own
// pre-merge review used and which rated season.spring/signal.buy's ~11.4
// as "close but not alarmingly so"), ΔE is a reasonable proxy for how
// different two colors actually *look* to a human viewer: classic
// color-science guidance treats ΔE ~2.3 as the just-noticeable difference
// under ideal viewing conditions, and ΔE below ~10 as "still read as the
// same color" by most viewers in typical (non-side-by-side-swatch)
// conditions. season.spring (#368139) and signal.buy (#2e7d32) -- the
// collision that prompted this guard -- computed to ΔE76 ~2.6, i.e.
// literally at the single-step JND, confirming they were practically
// indistinguishable rather than merely "a bit close".
//
// sRGB -> linear -> CIE XYZ (D65) -> CIE Lab, per the standard formulas
// (https://en.wikipedia.org/wiki/CIELAB_color_space).
function srgbToLinear(channel: number): number {
  const c = channel / 255
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

function hexToXyz(hex: string): [number, number, number] {
  const [r, g, b] = hexToRgb(hex).map(srgbToLinear)
  const x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
  const y = r * 0.2126729 + g * 0.7151522 + b * 0.072175
  const z = r * 0.0193339 + g * 0.119192 + b * 0.9503041
  return [x, y, z]
}

function labF(t: number): number {
  const delta = 6 / 29
  return t > delta ** 3 ? Math.cbrt(t) : t / (3 * delta ** 2) + 4 / 29
}

function hexToLab(hex: string): [number, number, number] {
  // D65 reference white
  const [xn, yn, zn] = [0.95047, 1.0, 1.08883]
  const [x, y, z] = hexToXyz(hex)
  const [fx, fy, fz] = [labF(x / xn), labF(y / yn), labF(z / zn)]
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)]
}

function deltaE76(hexA: string, hexB: string): number {
  const [l1, a1, b1] = hexToLab(hexA)
  const [l2, a2, b2] = hexToLab(hexB)
  return Math.sqrt((l1 - l2) ** 2 + (a1 - a2) ** 2 + (b1 - b2) ** 2)
}

// Floor for "these two colors read as clearly different swatches, not a
// near-miss" -- well above the ~2.3 single-step JND, and comfortably below
// the smallest ΔE76 between any two palette colors that are *actually*
// meant to be distinguishable at a glance in this app (~17.7, between
// season.summer and season.autumn -- see the assertions below).
const MIN_DISTINCT_DELTA_E = 15

function expectPerceptuallyDistinct(hexA: string, hexB: string): void {
  expect(deltaE76(hexA, hexB)).toBeGreaterThanOrEqual(MIN_DISTINCT_DELTA_E)
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

    // Exact-hex inequality (above) only catches an accidental literal
    // duplicate -- it wouldn't catch two colors that are technically
    // different hex values but read as the same color (see
    // frontend-indicator-seasons-badge-followups-followups). Every pair
    // here must also clear a real perceptual-distance floor.
    expectPerceptuallyDistinct(buy, sell)
    expectPerceptuallyDistinct(buy, hold)
    expectPerceptuallyDistinct(sell, hold)
  })

  it('defines a risk-breach color perceptually distinct from the sell signal color', () => {
    expect(theme.palette.riskBreach.main).toMatch(/^#/)
    expect(theme.palette.riskBreach.background).toMatch(/^#/)
    expect(theme.palette.riskBreach.main).not.toBe(theme.palette.signal.sell)
    // The original #d32f2f only cleared this by ~3.9 ΔE76 -- effectively
    // the same near-collision as season.spring/signal.buy, just missed by
    // this test's old exact-hex-only check (frontend-indicator-seasons-badge-followups-followups).
    expectPerceptuallyDistinct(theme.palette.riskBreach.main, theme.palette.signal.sell)
  })

  it('defines a divergence-marker color distinct from the BUY/SELL signal colors (frontend-divergence-markers)', () => {
    expect(theme.palette.divergence.main).toMatch(/^#/)
    expect(theme.palette.divergence.main).not.toBe(theme.palette.signal.buy)
    expect(theme.palette.divergence.main).not.toBe(theme.palette.signal.sell)
    expectPerceptuallyDistinct(theme.palette.divergence.main, theme.palette.signal.buy)
    expectPerceptuallyDistinct(theme.palette.divergence.main, theme.palette.signal.sell)
  })

  it('defines four distinct Indicator Season colors, none of which reuse or perceptually collide with a BUY/SELL/HOLD signal color (frontend-indicator-seasons-badge, frontend-indicator-seasons-badge-followups-followups)', () => {
    const { spring, summer, autumn, winter } = theme.palette.season
    const seasonColors = [spring, summer, autumn, winter]
    seasonColors.forEach((color) => expect(color).toMatch(/^#/))
    expect(new Set(seasonColors).size).toBe(4)

    const { buy, sell, hold } = theme.palette.signal
    seasonColors.forEach((color) => {
      expect(color).not.toBe(buy)
      expect(color).not.toBe(sell)
      expect(color).not.toBe(hold)
      // season.spring (#368139) and signal.buy (#2e7d32) used to pass the
      // exact-hex checks above while being only ~2.6 ΔE76 apart -- see this
      // task. Every season color must clear a real perceptual floor from
      // every signal color, not just an exact-hex mismatch.
      expectPerceptuallyDistinct(color, buy)
      expectPerceptuallyDistinct(color, sell)
      expectPerceptuallyDistinct(color, hold)
    })

    // The four season colors must also read as distinct from each other,
    // not just from the signal palette.
    for (let i = 0; i < seasonColors.length; i += 1) {
      for (let j = i + 1; j < seasonColors.length; j += 1) {
        expectPerceptuallyDistinct(seasonColors[i], seasonColors[j])
      }
    }
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
    expectPerceptuallyDistinct(main, theme.palette.signal.buy)
    expectPerceptuallyDistinct(main, theme.palette.signal.sell)
    expectPerceptuallyDistinct(main, theme.palette.divergence.main)
    expectPerceptuallyDistinct(main, theme.palette.riskBreach.main)
  })
})
