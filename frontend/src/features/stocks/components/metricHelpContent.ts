import { humanizeSnakeCase } from '../../../utils/format'
import { TIDE_INSUFFICIENT_HISTORY_OR_FLAT_SLOPE_HEDGE } from './tideNeutralCause'

/**
 * Shared help content for every metric shown on `StockDetailPage`
 * (`SignalSummary`/`ScreensPanel`/`IndicatorsPanel`) -- one entry per
 * metric, each grounded in a specific docs/Analyse.md section cited
 * directly in its own `definition`/`elderContext` text, so drift between
 * this file and the doc is easy to spot in a future review. Each entry
 * pairs a static `metricLabel`/`definition`/`elderContext` (fed to
 * `common/MetricHelp`) with its own `interpretValue` function -- typed to
 * that specific metric's actual value shape (a signal, a screen field, a
 * plain number, ...) rather than forced into one uniform
 * `(value: unknown) => string` signature, since the metrics here are
 * genuinely heterogeneous. Colocated with (but split out of) the
 * components that render it, same convention as `signalExplanation.ts`
 * (react-refresh/only-export-components).
 *
 * Feature module, not `common/`: every entry references an Elder Triple
 * Screen/confidence-scoring domain concept (Tide, Wave, Impulse,
 * confidence_breakdown component names), the same placement test
 * `signalExplanation.ts` and `ScreensPanel.tsx` already apply.
 */

// ---------------------------------------------------------------------------
// Signal + Confidence (SignalSummary.tsx)
// ---------------------------------------------------------------------------

export const signalHelp = {
  metricLabel: 'Signal',
  definition:
    'The Triple Screen trading signal for this ticker: BUY, SELL, or HOLD. Elder’s method never relies on one indicator alone -- this is the combined result of all three screens plus the Impulse System gate (docs/Analyse.md §1).',
  elderContext:
    'BUY requires Tide Bullish, Impulse not Red, a qualifying Wave pullback, and Trigger fired; SELL is the mirror image (Bearish Tide, Impulse not Green, a qualifying Wave rally, Trigger fired). Anything only partially met, or conflicting, is HOLD (docs/Analyse.md §5). Click the signal badge itself for the specific reasons behind *this* result -- this help explains what the three outcomes mean in general.',
  interpretValue(signal: 'BUY' | 'SELL' | 'HOLD'): string {
    if (signal === 'BUY') {
      return 'Currently BUY -- every Triple Screen condition lined up in the bullish direction for this ticker.'
    }
    if (signal === 'SELL') {
      return 'Currently SELL -- every Triple Screen condition lined up in the bearish direction for this ticker.'
    }
    return 'Currently HOLD -- at least one Triple Screen condition is unmet, or the Tide is Neutral, for this ticker right now.'
  },
}

export const confidenceHelp = {
  metricLabel: 'Confidence',
  definition:
    'A 0-100% weighted agreement score across the indicators behind the signal -- a rule-based composite, explicitly not a statistical probability (docs/Analyse.md §6).',
  elderContext:
    'Weighted from five components: Tide alignment 30%, Impulse gate 20%, Oscillator extremity 25%, Elder-Ray confirmation 15%, Volume confirmation 10% (docs/Analyse.md §6 -- see each breakdown row’s own help for what its score means). Displayed with a Low (<40%)/Medium (40-70%)/High (>70%) band alongside the raw percentage, since the band alone would lose precision.',
  interpretValue(confidence: number, band: 'Low' | 'Medium' | 'High'): string {
    return `Currently ${Math.round(confidence)}% -- ${band} confidence.`
  },
}

function interpretComponentScore(score: number, weight: number): string {
  const scorePct = Math.round(score * 100)
  const weightPct = Math.round(weight * 100)
  const contributionPoints = Math.round(score * weight * 100)
  return `Currently scored ${scorePct}% at a ${weightPct}% weight -- contributing ${contributionPoints} of the 100 possible confidence points.`
}

export const confidenceComponentHelp: Record<
  string,
  {
    metricLabel: string
    definition: string
    elderContext: string
    interpretValue: (score: number, weight: number) => string
  }
> = {
  tide_alignment: {
    metricLabel: 'Tide alignment (Screen 1)',
    definition:
      'How strongly the weekly MACD-Histogram slope and the 13/26-week EMA relationship agree with, and support, this signal’s direction.',
    elderContext:
      'Scored 100% if the weekly MACD-H slope and EMA13/26 relationship agree strongly, 50% if mixed, 0% if the Tide actually contradicts the signal direction (docs/Analyse.md §6). Weighted 30% -- the single largest component, reflecting Elder’s "never trade against the tide" rule.',
    interpretValue: interpretComponentScore,
  },
  impulse_gate: {
    metricLabel: 'Impulse gate',
    definition: 'How well the Impulse System’s color matches this signal’s direction.',
    elderContext:
      'Scored 100% if Impulse is Green for a BUY (or Red for a SELL), 40% if Blue (indicators disagree), 0% if the opposite color -- which should already have blocked a fresh signal in that direction (docs/Analyse.md §3, §6). Weighted 20%.',
    interpretValue: interpretComponentScore,
  },
  oscillator_extremity: {
    metricLabel: 'Oscillator extremity (Screen 2)',
    definition:
      'How deep into oversold/overbought territory the Wave’s Stochastic %K and Force Index reading are.',
    elderContext:
      'Scaled by depth -- e.g. Stochastic %K below 20 scores higher than %K below 30, since Elder reads a deeper extreme as a stronger counter-trend setup (docs/Analyse.md §2 Screen 2, §6). Weighted 25%.',
    interpretValue: interpretComponentScore,
  },
  elder_ray_confirmation: {
    metricLabel: 'Elder-Ray confirmation',
    definition:
      'Whether Bull Power / Bear Power confirm the exhaustion-then-reversal pattern Elder-Ray looks for around a pullback or rally.',
    elderContext:
      'Scored 100% when Bull/Bear Power confirm that pattern (docs/Analyse.md §2 Screen 2, §6). Weighted 15%.',
    interpretValue: interpretComponentScore,
  },
  volume_confirmation: {
    metricLabel: 'Volume confirmation',
    definition:
      'Whether the Force Index spike / trigger-bar volume is above its 20-day average, confirming genuine participation rather than a thin, unreliable move.',
    elderContext:
      'Scored 100% if volume confirms the spike/trigger (docs/Analyse.md §4, §6). Weighted 10% -- the smallest component, used as a confirming check rather than a primary driver.',
    interpretValue: interpretComponentScore,
  },
}

/** Looks up help content for a `confidence_breakdown` row by its `component` field, or `undefined` for a not-yet-documented future component name (same fallback posture `humanizeSnakeCase`'s `labelMap` already takes for this exact field). */
export function getConfidenceComponentHelp(component: string) {
  return confidenceComponentHelp[component]
}

// ---------------------------------------------------------------------------
// ScreensPanel.tsx
// ---------------------------------------------------------------------------

export const tideHelp = {
  metricLabel: 'Tide (Screen 1)',
  definition:
    'Screen 1 of the Triple Screen system: the dominant long-term trend, evaluated on the weekly chart. Elder’s rule is to never trade against the tide.',
  elderContext:
    'Driven by the weekly MACD-Histogram (12,26,9) slope -- rising means a bullish tide (only buy signals considered), falling means a bearish tide (only sell/avoid signals). Confirmed by the 13-week/26-week EMA relationship (13 EMA above 26 EMA = uptrend). Neutral when the slope and EMA relationship disagree -- this reduces confidence rather than blocking a signal outright (docs/Analyse.md §2 Screen 1).',
  interpretValue(trend: string, slope: string): string {
    const trendLabel = humanizeSnakeCase(trend)
    const slopeLabel = humanizeSnakeCase(slope).toLowerCase()
    if (trend === 'NEUTRAL') {
      // 'flat' is reported both when `evaluate_tide` (backend/app/signals/
      // triple_screen.py) computes a genuinely flat weekly MACD-H slope, and
      // -- via its <2-weekly-bar short-circuit -- when it never computes a
      // slope at all (too little weekly history yet). `TideScreen` doesn't
      // expose a weekly bar count, so this frontend can't tell those two
      // apart from `trend`/`slope` alone; naming both possibilities instead
      // of asserting "genuinely flat" avoids repeating the same
      // conflation-of-distinct-causes bug this branch itself was added to
      // fix (see this task's `decisions` entry).
      const cause =
        slope === 'flat'
          ? `${TIDE_INSUFFICIENT_HISTORY_OR_FLAT_SLOPE_HEDGE} -- either way, there’s no clear direction to read`
          : 'the weekly slope and EMA13/26 relationship disagree'
      // Omit the raw "(weekly MACD-H slope Flat)" parenthetical entirely
      // when slope === 'flat': stating it unqualified in the same sentence
      // that then hedges on whether a slope was ever computed at all would
      // assert, with full confidence, the exact reading this sentence is
      // simultaneously saying it can't be sure of (frontend-stock-detail-
      // metric-help-followups-followups task `decisions` entry). The
      // parenthetical stays for the disagree branch, where the slope value
      // itself (rising/falling) is never ambiguous.
      const slopeClause = slope === 'flat' ? '' : ` (weekly MACD-H slope ${slopeLabel})`
      return `Currently Neutral${slopeClause} -- ${cause}, so no directional Triple Screen setup is being evaluated for this ticker right now.`
    }
    const action = trend === 'BULLISH' ? 'buy' : 'sell'
    return `Currently ${trendLabel} (weekly MACD-H slope ${slopeLabel}) -- only fresh ${action} signals are considered while the tide holds this direction.`
  },
}

export const impulseHelp = {
  metricLabel: 'Impulse System',
  definition:
    'A per-bar color (Green/Red/Blue) from EMA(13) and the MACD-Histogram slope together, used as a hard gate on which actions are allowed right now.',
  elderContext:
    'Green (EMA13 rising and MACD-H rising) allows only buy or hold -- no new shorts. Red (EMA13 falling and MACD-H falling) allows only sell or hold -- no new buys. Blue means the two disagree -- any action is allowed, but signal strength is weaker (docs/Analyse.md §3).',
  interpretValue(impulse: string): string {
    if (impulse === 'GREEN') {
      return 'Currently GREEN -- only a fresh BUY or HOLD is allowed for this ticker; a fresh SELL is blocked regardless of Screen 2/3.'
    }
    if (impulse === 'RED') {
      return 'Currently RED -- only a fresh SELL or HOLD is allowed for this ticker; a fresh BUY is blocked regardless of Screen 2/3.'
    }
    return 'Currently BLUE -- EMA(13) and the MACD-Histogram slope disagree, so any action is technically allowed, but signal strength is weaker.'
  },
}

export const waveHelp = {
  metricLabel: 'Wave (Screen 2)',
  definition:
    'Screen 2 of the Triple Screen system: within the tide’s direction, oscillators time entries by waiting for a counter-trend dip (in a bullish tide) or rally (in a bearish tide).',
  elderContext:
    'Stochastic %K (5,3,3) below 30 is oversold, above 70 is overbought. Force Index (2-period EMA) spiking negative in an uptrend is a buying opportunity; spiking positive in a downtrend is a selling opportunity (docs/Analyse.md §2 Screen 2, §4).',
  interpretValue(
    stochasticK: number | null | undefined,
    forceIndex: number | null | undefined,
    state: string,
  ): string {
    const stochasticKnown =
      stochasticK !== null && stochasticK !== undefined && !Number.isNaN(stochasticK)
    const stochasticNote = !stochasticKnown
      ? 'Stochastic %K is currently unavailable'
      : stochasticK < 30
        ? `Stochastic %K of ${stochasticK.toFixed(1)} is oversold (below 30)`
        : stochasticK > 70
          ? `Stochastic %K of ${stochasticK.toFixed(1)} is overbought (above 70)`
          : `Stochastic %K of ${stochasticK.toFixed(1)} is in the neutral zone (30-70): neither overbought nor oversold`
    const forceIndexKnown =
      forceIndex !== null && forceIndex !== undefined && !Number.isNaN(forceIndex)
    const forceIndexNote = !forceIndexKnown
      ? ''
      : forceIndex < 0
        ? ' Force Index is negative, i.e. selling pressure today.'
        : forceIndex > 0
          ? ' Force Index is positive, i.e. buying pressure today.'
          : ' Force Index is flat.'
    return `${stochasticNote}.${forceIndexNote} Wave state: ${humanizeSnakeCase(state)}.`
  },
}

export const triggerHelp = {
  metricLabel: 'Trigger (Screen 3)',
  definition:
    'Screen 3 of the Triple Screen system: precise entry timing once the Tide and Wave align -- confirms price has actually resumed the tide’s direction.',
  elderContext:
    'Elder’s classic trigger is a stop placed just above the prior day’s high (uptrend) or below the prior day’s low (downtrend); this daily-bar app approximates it as today’s close crossing back above the prior day’s high (bullish) or below the prior day’s low (bearish) (docs/Analyse.md §2 Screen 3).',
  interpretValue(fired: boolean, reference: string, tideTrend: string): string {
    if (fired) {
      return `Fired -- ${humanizeSnakeCase(reference)}, confirming the tide’s direction has resumed.`
    }
    if (reference === 'not_applicable') {
      if (tideTrend === 'NEUTRAL') {
        return 'Not applicable -- the Tide is Neutral, so there is no directional high/low to trigger against right now (a Trigger only evaluates once Screen 1 has a Bullish or Bearish tide).'
      }
      return 'Not fired -- there isn’t enough daily price history yet to compare today’s close against a prior high/low.'
    }
    return `Not fired yet -- reference: ${humanizeSnakeCase(reference)}.`
  },
}

// ---------------------------------------------------------------------------
// IndicatorsPanel.tsx
// ---------------------------------------------------------------------------

function isKnown(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && !Number.isNaN(value)
}

export const ema13Help = {
  metricLabel: 'EMA (13)',
  definition:
    'The 13-period Exponential Moving Average of closing price -- a short-term trend-following average.',
  elderContext:
    'Feeds both the Tide (13-week/26-week EMA relationship, §2 Screen 1) and the Impulse System (EMA13 rising/falling is half of its Green/Red gate, §3). Also the baseline Elder-Ray measures Bull/Bear Power against (§2 Screen 2, §4).',
  interpretValue(
    ema13: number | null | undefined,
    ema26: number | null | undefined,
  ): string {
    if (!isKnown(ema13)) {
      return 'Currently unavailable for this ticker.'
    }
    if (!isKnown(ema26)) {
      return `Currently ${ema13.toFixed(2)}.`
    }
    const relation = ema13 > ema26 ? 'above' : ema13 < ema26 ? 'below' : 'equal to'
    const reading =
      ema13 > ema26
        ? 'an uptrend reading'
        : ema13 < ema26
          ? 'a downtrend reading'
          : 'a flat reading'
    return `Currently ${ema13.toFixed(2)}, ${relation} EMA(26) (${ema26.toFixed(2)}) -- Elder reads 13 EMA above 26 EMA as an uptrend, so this is ${reading} (docs/Analyse.md §2).`
  },
}

export const ema26Help = {
  metricLabel: 'EMA (26)',
  definition:
    'The 26-period Exponential Moving Average of closing price -- the longer of the two trend-following averages Elder pairs together.',
  elderContext:
    'Paired with EMA(13) as the Tide’s secondary trend confirmation: 13 EMA above 26 EMA reads as an uptrend, below as a downtrend (docs/Analyse.md §2 Screen 1).',
  interpretValue(
    ema26: number | null | undefined,
    ema13: number | null | undefined,
  ): string {
    if (!isKnown(ema26)) {
      return 'Currently unavailable for this ticker.'
    }
    if (!isKnown(ema13)) {
      return `Currently ${ema26.toFixed(2)}.`
    }
    const relation = ema13 > ema26 ? 'above' : ema13 < ema26 ? 'below' : 'equal to'
    return `Currently ${ema26.toFixed(2)}; EMA(13) is ${relation} it -- Elder reads 13 EMA above 26 EMA as an uptrend, below as a downtrend (docs/Analyse.md §2).`
  },
}

export const macdHistogramHelp = {
  metricLabel: 'MACD Histogram',
  definition:
    'The 12/26/9 MACD Histogram: the difference between the MACD line and its 9-period signal line, on the daily chart.',
  elderContext:
    'Its slope (not just sign) is the momentum half of the daily Impulse System gate -- rising alongside a rising EMA(13) turns the bar Green, falling alongside a falling EMA(13) turns it Red (docs/Analyse.md §3). The weekly version of the same indicator drives the Tide (§2 Screen 1).',
  interpretValue(value: number | null | undefined): string {
    if (!isKnown(value)) {
      return 'Currently unavailable for this ticker.'
    }
    if (value > 0) {
      return `Currently ${value.toFixed(2)} -- positive, i.e. MACD is above its signal line (bullish momentum). Note this single value doesn’t show slope; the Impulse gate depends on whether it’s rising or falling over time, not just this sign.`
    }
    if (value < 0) {
      return `Currently ${value.toFixed(2)} -- negative, i.e. MACD is below its signal line (bearish momentum). Note this single value doesn’t show slope; the Impulse gate depends on whether it’s rising or falling over time, not just this sign.`
    }
    return 'Currently 0.00 -- MACD is exactly at its signal line.'
  },
}

export const bullPowerHelp = {
  metricLabel: 'Bull Power',
  definition: 'Elder-Ray’s buyer-strength measure: Bull Power = High − EMA(13).',
  elderContext:
    'In a downtrend, Elder looks for Bull Power positive but falling as a sell cue -- buyers can still push price above the average, but with less and less force (docs/Analyse.md §2 Screen 2, §4).',
  interpretValue(value: number | null | undefined): string {
    if (!isKnown(value)) {
      return 'Currently unavailable for this ticker.'
    }
    if (value > 0) {
      return `Currently ${value.toFixed(2)} -- positive: today’s high traded above EMA(13), i.e. buyers pushed price above the average.`
    }
    return `Currently ${value.toFixed(2)} -- negative or zero: today’s high stayed at or below EMA(13), i.e. buyers couldn’t push price above the average today.`
  },
}

export const bearPowerHelp = {
  metricLabel: 'Bear Power',
  definition: 'Elder-Ray’s seller-strength measure: Bear Power = Low − EMA(13).',
  elderContext:
    'In an uptrend, Elder looks for Bear Power negative but rising as a buy cue -- sellers can still push price below the average on a dip, but with less and less force each time (docs/Analyse.md §2 Screen 2, §4).',
  interpretValue(value: number | null | undefined): string {
    if (!isKnown(value)) {
      return 'Currently unavailable for this ticker.'
    }
    if (value < 0) {
      return `Currently ${value.toFixed(2)} -- negative: today’s low traded below EMA(13), the normal/expected reading even in an uptrend (Elder’s buy cue is this value rising over time, not becoming positive).`
    }
    return `Currently ${value.toFixed(2)} -- positive or zero: today’s low stayed at or above EMA(13), i.e. sellers couldn’t push price below the average today -- an unusually strong bullish reading.`
  },
}
