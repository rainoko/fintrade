import type {
  DivergenceOut,
  FalseBreakoutOut,
  HistoryResponse,
  IndicatorHistoryPoint,
  KangarooTailOut,
  SupportResistanceZone,
} from '../../../api/stocks'
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

export const seasonHelp = {
  metricLabel: 'Indicator Season',
  definition:
    'A four-way Spring/Summer/Autumn/Winter classification of the daily MACD-Histogram’s current state: its bar-over-bar slope (rising/falling) combined with its position relative to its own zero centerline (docs/Analyse.md row 12, Elder ch. 32 "Time"). Purely informational -- unlike Tide/Impulse/Wave/Trigger above, it is not read by the BUY/SELL/HOLD signal or the confidence score at all.',
  elderContext:
    'Spring = rising and below centerline, Summer = rising and above, Autumn = falling and above, Winter = falling and below. Elder’s own point in applying "seasons" to an indicator isn’t just the taxonomy -- it’s that Spring and Autumn are the best risk/reward entries precisely because they’re the hardest to act on emotionally: in Spring, "memories of the downtrend are still fresh," so most traders stay sidelined or keep shorting even as the indicator has already turned up; Summer and Winter feel comfortable to trade because the crowd has caught on by then, which is exactly why they’re worse value -- you’re buying (Summer) or selling (Winter) after the move, alongside everyone else, not ahead of it. The Impulse System’s Green/Red/Blue (above) answers a different question -- what’s allowed right now -- while this reads the oscillator’s maturity within its current swing.',
  interpretValue(
    season: 'Spring' | 'Summer' | 'Autumn' | 'Winter' | null | undefined,
  ): string {
    if (!season) {
      return 'Currently unavailable for this ticker -- fewer than 2 daily bars are available yet to compute a slope from.'
    }
    if (season === 'Spring') {
      return 'Currently Spring -- MACD-Histogram is rising but still below its own zero centerline. Elder’s own read: this is the best risk/reward entry for a long, but also the hardest to take emotionally, since it still looks and feels like the downtrend that just ended.'
    }
    if (season === 'Autumn') {
      return 'Currently Autumn -- MACD-Histogram is falling but still above its own zero centerline. Elder’s own read: this is the best risk/reward entry for a short, but also the hardest to take emotionally, since it still looks and feels like the uptrend that just ended.'
    }
    if (season === 'Summer') {
      return 'Currently Summer -- MACD-Histogram is rising and above its own zero centerline: a crowd-recognized uptrend. Feels comfortable to buy here, which is exactly why Elder rates it a worse-value entry than Spring -- the easy gains already happened.'
    }
    return 'Currently Winter -- MACD-Histogram is falling and below its own zero centerline: a crowd-recognized downtrend. Feels comfortable to sell/short here, which is exactly why Elder rates it a worse-value entry than Autumn -- the easy gains already happened.'
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

// ---------------------------------------------------------------------------
// OscillatorChart.tsx (frontend-rsi-oscillator-chart)
// ---------------------------------------------------------------------------

export const rsiHelp = {
  metricLabel: 'RSI (9)',
  definition:
    'Relative Strength Index over a 9-day window: RSI = 100 - 100 / (1 + RS), where RS is the average of net up-closes divided by the average of net down-closes over that window -- a closing-price-only momentum oscillator, 0-100 bounded like Stochastic (docs/Analyse.md §4, Elder ch. 27).',
  elderContext:
    'Unlike Stochastic %K (which also reads each bar’s high/low), RSI looks only at closing prices -- Elder’s own side-by-side comparison (ch. 27) calls RSI "less noisy" than Stochastic, with signals that tend to emerge earlier on the same data. Both are plotted here on the same pane/0-100 scale, with the same 30/70 oversold/overbought reference lines, specifically so the two can be read against each other directly -- Elder treats them as worth watching together, not RSI as a redundant second copy of Stochastic. Computation + exposure only: RSI isn’t currently wired into Screen 2’s Wave state machine or confidence scoring (docs/Analyse.md row 10; see the backend-indicator-rsi task).',
  interpretValue(
    rsi: number | null | undefined,
    stochasticK: number | null | undefined,
  ): string {
    if (!isKnown(rsi)) {
      return 'Currently unavailable for this ticker -- the 9-day warm-up window hasn’t been reached yet.'
    }
    const zone =
      rsi < 30
        ? 'oversold (below 30)'
        : rsi > 70
          ? 'overbought (above 70)'
          : 'in the neutral zone (30-70): neither overbought nor oversold'
    if (!isKnown(stochasticK)) {
      return `Currently ${rsi.toFixed(1)}, ${zone}.`
    }
    const gap = Math.abs(rsi - stochasticK)
    const comparison =
      gap < 10
        ? `broadly agreeing with Stochastic %K (${stochasticK.toFixed(1)}) right now`
        : `reading ${rsi > stochasticK ? 'stronger' : 'weaker'} than Stochastic %K (${stochasticK.toFixed(1)}) right now, since RSI reacts only to closing prices while Stochastic also reads the high/low range -- exactly the divergence between them Elder's own comparison describes`
    return `Currently ${rsi.toFixed(1)}, ${zone} -- ${comparison}.`
  },
}

// ---------------------------------------------------------------------------
// Channel / value-zone overlay (PriceChart.tsx)
// ---------------------------------------------------------------------------

export const channelHelp = {
  metricLabel: 'Channel (Autoenvelope)',
  definition:
    'A symmetric percentage envelope around EMA(13) -- upper/lower bands sized, from the last ~100 trading days of deviation, to contain roughly 95% of recent daily closes (docs/Analyse.md §4; Elder ch. 41 "Channel Trading Systems").',
  elderContext:
    'This is the exact band `evaluate_exit_flags` (backend/app/portfolio/exits.py) already checks internally for an existing position’s "price reaches the upper Autoenvelope band with Impulse turning Red" profit-taking exit rule (docs/Analyse.md §7) -- previously only computed for a held portfolio position, now shown for any ticker. Elder’s own read of the bands is contrarian, not momentum-chasing: buy near the lower band, sell/take profit near the upper one (ch. 41).',
  interpretValue(
    channelUpper: number | null | undefined,
    channelLower: number | null | undefined,
    latestClose: number | null | undefined,
  ): string {
    if (!isKnown(channelUpper) || !isKnown(channelLower)) {
      return 'Currently unavailable for this ticker -- the Autoenvelope’s ~100-trading-day rolling deviation-average warm-up window hasn’t been reached yet.'
    }
    const halfWidthPct =
      ((channelUpper - channelLower) / (channelUpper + channelLower)) * 100
    const bounds = `${channelLower.toFixed(2)}-${channelUpper.toFixed(2)} (±${halfWidthPct.toFixed(1)}% around EMA(13))`
    if (!isKnown(latestClose)) {
      return `Currently ${bounds}.`
    }
    if (latestClose >= channelUpper) {
      return `Currently ${bounds} -- the latest close (${latestClose.toFixed(2)}) is at or above the upper band, Elder’s profit-taking/overextension zone.`
    }
    if (latestClose <= channelLower) {
      return `Currently ${bounds} -- the latest close (${latestClose.toFixed(2)}) is at or below the lower band, Elder’s contrarian buying zone.`
    }
    const positionPct =
      ((latestClose - channelLower) / (channelUpper - channelLower)) * 100
    return `Currently ${bounds} -- the latest close (${latestClose.toFixed(2)}) sits ${positionPct.toFixed(0)}% of the way from the lower to the upper band, inside the channel.`
  },
}

export const valueZoneHelp = {
  metricLabel: 'Value Zone (EMA 13-26)',
  definition:
    'The shaded zone between the fast (13-period) and slow (26-period) EMA -- Elder names this the "value zone" (ch. 41): the area a price that has pulled away from it is expected to return to.',
  elderContext:
    'This exact EMA13/EMA26 pair already drives the Tide (Screen 1), the Impulse System gate, and the Elder-Ray baseline elsewhere on this page (docs/Analyse.md §2-4) -- also plotted as the two solid trend lines on this same chart. Elder calls the zone between them a good swing-trade profit target ("the value zone on a weekly chart presents a good target," ch. 38/53) -- this app doesn’t yet compute an explicit target price from it (a separate, still-open task), so today this shading is informational, not a live target or stop input.',
  interpretValue(
    ema13: number | null | undefined,
    ema26: number | null | undefined,
  ): string {
    if (!isKnown(ema13) || !isKnown(ema26)) {
      return 'Currently unavailable for this ticker.'
    }
    const lower = Math.min(ema13, ema26)
    const upper = Math.max(ema13, ema26)
    const reading =
      ema13 > ema26
        ? 'an uptrend reading'
        : ema13 < ema26
          ? 'a downtrend reading'
          : 'a flat reading'
    return `Currently ${lower.toFixed(2)}-${upper.toFixed(2)} (EMA13 ${ema13 > ema26 ? 'above' : ema13 < ema26 ? 'below' : 'equal to'} EMA26 -- ${reading}).`
  },
}

// ---------------------------------------------------------------------------
// Support/resistance zone overlay (PriceChart.tsx, frontend-support-
// resistance-overlay)
// ---------------------------------------------------------------------------

/** Distance (in price units) from `price` to the nearest edge of `zone` --
 * `0` when `price` sits inside `[lower, upper]`. Used to find the zone
 * closest to the ticker's latest close for `supportResistanceZoneHelp`'s
 * current-value interpretation. */
function distanceToZone(price: number, zone: SupportResistanceZone): number {
  if (price >= zone.lower && price <= zone.upper) {
    return 0
  }
  return Math.min(Math.abs(price - zone.lower), Math.abs(price - zone.upper))
}

export const supportResistanceZoneHelp = {
  metricLabel: 'Support/Resistance Zones',
  definition:
    'Horizontal price bands where this ticker has repeatedly stalled -- built from the closing prices of clustered swing highs/lows, not the single most extreme wick that happened to touch the level once (Elder ch. 18).',
  elderContext:
    'Strength is scored from how long the zone has persisted (length: ~2 weeks minor, ~2 months intermediate, ~2 years major) and how wide it is as a percentage of price (height: ~1%/~3%/>=7%) -- shaded more strongly here the higher that score, so a major, long-lived zone reads as more visually prominent than a weak, recent one. A zone whose role has flipped after a confirmed break (dashed border here) keeps existing with its role inverted -- old resistance becomes new support, and vice versa -- rather than being discarded (docs/Analyse.md §4 row 9). Up to 6 of the strongest zones are shown here, out of up to 15 this app detects per ticker.',
  interpretValue(
    zones: readonly SupportResistanceZone[],
    displayedZones: readonly SupportResistanceZone[],
    latestClose: number | null | undefined,
  ): string {
    if (zones.length === 0) {
      return 'No support/resistance zones detected yet for this ticker -- needs at least 2 clustered swing-point touches spanning 14+ days.'
    }
    const shown = `Showing ${displayedZones.length} of ${zones.length} detected zone${zones.length === 1 ? '' : 's'} (strongest first).`
    if (!isKnown(latestClose) || displayedZones.length === 0) {
      return shown
    }
    // Nearest is found among `displayedZones` (relevance-filtered + capped
    // -- see `PriceChart.tsx`'s `selectDisplayedZones`), NOT the raw `zones`
    // list, so this reading can never name a zone that isn't actually drawn
    // on the chart (post-review fix, PR #152 retry round 2 -- see the
    // caller's own comment for the AAPL/MSFT/AMD mismatch this fixes).
    const nearest = displayedZones.reduce((closest, zone) =>
      distanceToZone(latestClose, zone) < distanceToZone(latestClose, closest)
        ? zone
        : closest,
    )
    const roleLabel = nearest.role === 'support' ? 'Support' : 'Resistance'
    const flipped = nearest.broken ? ', role flipped after a confirmed break' : ''
    return `${shown} Nearest to the latest close (${latestClose.toFixed(2)}): ${roleLabel} ${nearest.lower.toFixed(2)}-${nearest.upper.toFixed(2)} (${humanizeSnakeCase(nearest.height_category)} height, ${humanizeSnakeCase(nearest.length_category)} length${flipped}).`
  },
}

interface ZoneWithFalseBreakout extends SupportResistanceZone {
  false_breakout: FalseBreakoutOut
}

function hasFalseBreakout(zone: SupportResistanceZone): zone is ZoneWithFalseBreakout {
  return zone.false_breakout != null
}

/**
 * The most recent (by `reentry_date`) false-breakout episode among
 * `displayedZones` -- the same relevance-filtered + capped list the
 * chart-drawing effect actually renders (`PriceChart.tsx`'s
 * `selectDisplayedZones`), not the raw API response, so this can never pick
 * a zone that isn't actually on the chart (post-review fix, PR #152 retry
 * round 2). `undefined` when none of `displayedZones` has a false breakout
 * at all.
 *
 * Exported (not inlined into `falseBreakoutHelp.interpretValue` below) so
 * `PriceChart.tsx` can run this exact same selection to decide whether the
 * episode `interpretValue` is about to describe is also the one
 * `buildFalseBreakoutMarkers` actually windows onto the chart -- the same
 * "one shared function so two computations can't drift" pattern
 * `selectDisplayedZones` itself already established for the zone list, per
 * this task's `decisions` entry.
 */
export function mostRecentFalseBreakoutZone(
  displayedZones: readonly SupportResistanceZone[],
): ZoneWithFalseBreakout | undefined {
  const withBreakout = displayedZones.filter(hasFalseBreakout)
  if (withBreakout.length === 0) {
    return undefined
  }
  return withBreakout.reduce((latest, zone) =>
    zone.false_breakout.reentry_date > latest.false_breakout.reentry_date ? zone : latest,
  )
}

export const falseBreakoutHelp = {
  metricLabel: 'False Breakout',
  definition:
    'A specific reversal setup, not just noise: price closes beyond a support/resistance zone, then closes back inside it within about two trading weeks.',
  elderContext:
    'Elder ch. 18 calls a false breakout "a specific, high-value trade setup" -- the market tested a level, failed to hold beyond it, and is now more likely to reverse. The book\'s explicit stop-placement rule is to place a stop near the failed move\'s own extreme (the highest high reached for a failed break up, the lowest low for a failed break down) -- not further out, since that extreme is exactly how far the market proved it could reach before reversing. Marked on the chart with a distinct marker at the close that confirmed the reversal, plus a dashed price line at that extreme.',
  /**
   * `inVisibleRange` (this task's follow-up fix, mirroring
   * `divergenceHelp.interpretValue`/`kangarooTailHelp.interpretValue`'s own
   * parameter): whether the most-recent breakout's own `reentry_date` falls
   * within the chart's currently selected/visible bar range -- the same
   * `firstDate`/`lastDate` window `buildFalseBreakoutMarkers` and the dashed
   * "False-breakout stop" price line are both already windowed to
   * (`PriceChart.tsx`). Defaults to `true` so every existing caller
   * (including this file's own tests, which don't care about range-
   * windowing) doesn't need to think about a range at all.
   *
   * Decision (this task's `decisions` entry): follows the divergence/
   * Kangaroo Tail precedent -- still names the real episode in full and
   * appends a caveat clause when it isn't currently drawn, rather than
   * filtering the search itself to only in-range breakouts (which would
   * make the legend claim "no false breakouts" for a zone that genuinely
   * has one, just outside the current range/window selection).
   */
  interpretValue(
    displayedZones: readonly SupportResistanceZone[],
    inVisibleRange = true,
  ): string {
    const mostRecent = mostRecentFalseBreakoutZone(displayedZones)
    if (!mostRecent) {
      return 'No false breakouts detected among these zones right now.'
    }
    const { false_breakout: breakout } = mostRecent
    const roleLabel = mostRecent.role === 'support' ? 'support' : 'resistance'
    const directionLabel = breakout.direction === 'up' ? 'broke above' : 'broke below'
    const rangeClause = inVisibleRange
      ? ''
      : ` This false breakout isn't marked on the chart right now -- its reentry date (${breakout.reentry_date}) falls outside the currently selected range. Switch to a wider range (e.g. 1Y or Max) to see it plotted.`
    return `Most recent: the ${roleLabel} zone ${mostRecent.lower.toFixed(2)}-${mostRecent.upper.toFixed(2)} ${directionLabel} it on ${breakout.breakout_date}, then closed back inside by ${breakout.reentry_date} -- suggested stop near ${breakout.extreme_price.toFixed(2)}, the failed move's own extreme.${rangeClause}`
  },
}

// ---------------------------------------------------------------------------
// Divergence overlay (PriceChart.tsx/OscillatorChart.tsx,
// frontend-divergence-markers)
// ---------------------------------------------------------------------------

const DIVERGENCE_INDICATOR_LABEL: Record<DivergenceOut['indicator'], string> = {
  macd_histogram: 'MACD-Histogram',
  stochastic: 'Stochastic %K',
  rsi: 'RSI',
}

export const divergenceHelp = {
  metricLabel: 'Divergence',
  definition:
    'Price makes a new extreme (a lower low, or a higher high) that an oscillator does NOT confirm with a matching new extreme of its own -- a sign the move driving price is losing the momentum behind it, even though price itself hasn’t turned yet.',
  elderContext:
    'Elder calls divergences "some of the most powerful signals in technical analysis" (docs/ideas.md). A bullish divergence (two successive price swing LOWS, the second with a shallower oscillator reading) is a potential buy setup; a bearish divergence (two successive swing HIGHS) is a potential sell setup. For MACD-Histogram, the oscillator must cross back through its own zero centerline between the two extremes -- "an absolute must for a true divergence" per the book, checked as a hard requirement here, not just a strength cue. Stochastic/RSI have no centerline requirement, but read strongest when the first extreme sits beyond the oscillator’s own 30/70 oversold/overbought reference line and the second is back inside it. Also implements Kerry Lovvorn’s empirical refinement: the two extremes must be 20-40 trading days apart, and the second no more than half the height/depth of the first -- a closer/further-apart or deeper-than-half pair is never reported as a divergence at all. If price later ignores a formed divergence (a new low past the bullish divergence’s own second extreme, or a new high past the bearish one’s), Elder treats that ("Hound of the Baskervilles") as a strong continuation signal in the *opposite* direction, not a failed signal to discard -- his one explicit stop-and-reverse case.',
  /**
   * `inVisibleRange` (post-review fix, PR #158): whether `divergence`'s own
   * two extreme dates both fall within the chart's currently selected/
   * visible bar range -- see `divergenceClick.ts#isDivergenceInRange`, which
   * both `PriceChart.tsx` and `OscillatorChart.tsx` compute and pass here.
   * Defaults to `true` so every existing caller (including this app's own
   * `metricHelpContent.test.ts`, which only cares about the divergence's own
   * content, not range-windowing) doesn't need to think about a range at
   * all. When `false`, the overlay's own connecting line/markers are NOT
   * drawn on the chart (see `isDivergenceInRange`'s own doc comment for why
   * -- an out-of-range point distorts the chart's time scale) -- this
   * function still names the actual divergence in full (Decision, this
   * task's `decisions` entry: a real, currently-qualifying divergence stays
   * worth surfacing even when the user's current range selection happens to
   * exclude it, unlike `supportResistanceZoneHelp`'s zone legend, which
   * hides entirely once nothing survives its own relevance filter/cap -- a
   * *permanent* exclusion for that ticker, not a temporary range choice) and
   * appends a clause explaining why nothing is currently drawn.
   */
  interpretValue(divergence: DivergenceOut | null, inVisibleRange = true): string {
    if (!divergence) {
      return 'No currently qualifying divergence detected for this ticker.'
    }
    const indicatorLabel = DIVERGENCE_INDICATOR_LABEL[divergence.indicator]
    const kindLabel = divergence.kind === 'bullish' ? 'Bullish' : 'Bearish'
    const swingLabel = divergence.kind === 'bullish' ? 'swing lows' : 'swing highs'
    const implication =
      divergence.kind === 'bullish'
        ? 'a potential buy setup -- selling momentum is fading even as price makes a new low'
        : 'a potential sell setup -- buying momentum is fading even as price makes a new high'
    const first = `${divergence.first_extreme_date} (price ${divergence.first_extreme_price.toFixed(2)}, ${indicatorLabel} ${divergence.first_extreme_indicator_value.toFixed(2)})`
    const second = `${divergence.second_extreme_date} (price ${divergence.second_extreme_price.toFixed(2)}, ${indicatorLabel} ${divergence.second_extreme_indicator_value.toFixed(2)})`
    const validityClause =
      divergence.indicator === 'macd_histogram'
        ? `${indicatorLabel} crossed back through its own zero centerline between the two dates, the required confirmation for a true MACD-Histogram divergence.`
        : divergence.beyond_reference_line
          ? `The first extreme’s ${indicatorLabel} reading was beyond the 30/70 reference line and the second was back inside it -- this divergence’s textbook-strongest form.`
          : `${indicatorLabel} has no centerline requirement, but this pair didn’t reach beyond the 30/70 reference line on the first extreme -- still a qualifying divergence, just not its strongest form.`
    const spacingClause = `The two extremes are ${divergence.bars_apart} trading days apart (Kerry Lovvorn’s empirical 20-40-day window).`
    const abortedClause = divergence.aborted
      ? ` "Hound of the Baskervilles": price has since closed beyond the second extreme’s own level in the opposite direction of what this divergence implied -- Elder reads this as a strong continuation signal the other way, not a failed divergence to ignore.`
      : ''
    const rangeClause = inVisibleRange
      ? ''
      : ` This divergence isn’t drawn on the chart right now -- its own dates (${divergence.first_extreme_date} to ${divergence.second_extreme_date}) fall outside the currently selected range. Switch to a wider range (e.g. 1Y or Max) to see it plotted.`
    return `${kindLabel} ${indicatorLabel} divergence, comparing two successive price ${swingLabel}: ${first} vs ${second}. ${validityClause} ${spacingClause} Implies ${implication}.${abortedClause}${rangeClause}`
  },
}

// ---------------------------------------------------------------------------
// Kangaroo Tail overlay (PriceChart.tsx, frontend-kangaroo-tail-markers)
// ---------------------------------------------------------------------------

export const kangarooTailHelp = {
  metricLabel: 'Kangaroo Tail',
  definition:
    'A 3-bar reversal pattern (Elder ch. 20, "fingers"): a single bar whose range is roughly 2.5x the recent average, protruding from a tight recent range, where the close ends up back near the open -- not at the tip the bar spiked to -- flanked by two bars of normal height.',
  elderContext:
    'An upward-pointing tail (a new high, closing back down) is a bearish reversal signal; a downward-pointing tail (a new low, closing back up) is bullish. Elder\'s explicit stop-placement rule is halfway through the tail -- not at its tip (too wide) or its base (too tight). This app requires the very next bar to confirm the reversal (closing beyond the tail\'s own close, in the implied direction) before ever reporting a tail at all -- an unconfirmed shape-only candidate is never shown (docs/Analyse.md row 13).',
  /**
   * `tailBar` -- the tail bar's own `open`/`close`, looked up by
   * `tail.tail_date` from the currently-fetched `/history` bars (`bars` in
   * `PriceChart.tsx`), since `KangarooTailOut` itself only exposes
   * `high`/`low` (the backend detection algorithm never needed open/close
   * -- see the `backend-kangaroo-tail-pattern` task's `decisions`), but this
   * task's own explanation requirement ("why the close snapping back to the
   * open matters... using this ticker's own actual numbers") needs both.
   * `undefined` whenever the tail bar's date isn't covered by the currently
   * selected range/interval (a genuinely different situation from
   * `inVisibleRange` below -- `tailBar` can be missing even when the tail
   * IS in range, on a first render before `/history` resolves) -- degrades
   * to describing the pattern from `high`/`low`/`range_multiple`/
   * `suggested_stop` alone rather than omitting the explanation entirely.
   *
   * `inVisibleRange` -- same convention as `divergenceHelp.interpretValue`'s
   * own parameter: whether `tail.tail_date` falls within the chart's
   * currently selected/visible bar range (see `isKangarooTailInRange`,
   * `PriceChart.tsx`). Defaults to `true` so callers that don't care about
   * range-windowing (this file's own tests) don't need to think about it.
   */
  interpretValue(
    tail: KangarooTailOut | null,
    tailBar: HistoryResponse['bars'][number] | undefined,
    inVisibleRange = true,
  ): string {
    if (!tail) {
      return 'No currently confirmed Kangaroo Tail pattern detected for this ticker.'
    }
    const directionLabel =
      tail.direction === 'up' ? 'Bearish (upward-pointing)' : 'Bullish (downward-pointing)'
    const barRange = tail.high - tail.low
    const avgRange = tail.range_multiple > 0 ? barRange / tail.range_multiple : barRange
    const rangeClause = `On ${tail.tail_date}, this bar's own range was ${barRange.toFixed(2)} (high ${tail.high.toFixed(2)}, low ${tail.low.toFixed(2)}) -- ${tail.range_multiple.toFixed(1)}x the ~${avgRange.toFixed(2)} average range of the preceding 10 trading days, well beyond the 2.5x this pattern requires.`
    const oppositeExtremeLabel = tail.direction === 'up' ? 'low' : 'high'
    const spikeExtremeLabel = tail.direction === 'up' ? 'high' : 'low'
    const bodyClause =
      tailBar != null
        ? ` Its open (${tailBar.open.toFixed(2)}) and close (${tailBar.close.toFixed(2)}) both snapped back into the half of that range nearest the ${oppositeExtremeLabel} -- not the new ${spikeExtremeLabel} the bar actually spiked to -- which is exactly what separates a Kangaroo Tail from an ordinary big trend day.`
        : ''
    const confirmClause = ` Confirmed on ${tail.confirmed_date}, when the very next bar's own close continued ${tail.direction === 'up' ? 'below' : 'above'} this bar's close -- the hard confirmation gate this pattern requires before it's ever reported at all.`
    const tip = tail.direction === 'up' ? tail.high : tail.low
    const base = tail.direction === 'up' ? tail.low : tail.high
    const stopClause = ` Suggested stop: ${tail.suggested_stop.toFixed(2)} -- halfway through the tail (this bar's own high-low midpoint), not at the tip (${tip.toFixed(2)}, too wide) or the base (${base.toFixed(2)}, too tight).`
    const rangeVisibilityClause = inVisibleRange
      ? ''
      : ` This tail isn't marked on the chart right now -- ${tail.tail_date} falls outside the currently selected range. Switch to a wider range (e.g. 1Y or Max) to see it plotted.`
    return `${directionLabel} Kangaroo Tail. ${rangeClause}${bodyClause}${confirmClause}${stopClause}${rangeVisibilityClause}`
  },
}

// ---------------------------------------------------------------------------
// Tide (Screen 1) background shading (PriceChart.tsx,
// frontend-tide-region-chart-shading)
// ---------------------------------------------------------------------------

/**
 * Tallies how many of `points` (the exact windowed/visible dataset
 * `PriceChart.tsx`'s tide-shading effect actually draws from --
 * `selectVisibleIndicatorPoints`, not the raw unwindowed `/indicators`
 * response) fall into each of the three `TideScreen.trend` values. Exported
 * so `tideRegionHelp.interpretValue` and any future consumer share one
 * counting pass rather than duplicating the loop.
 */
export function countTideTrends(
  points: readonly IndicatorHistoryPoint[],
): { bullish: number; bearish: number; neutral: number } {
  let bullish = 0
  let bearish = 0
  let neutral = 0
  for (const point of points) {
    if (point.tide.trend === 'BULLISH') {
      bullish += 1
    } else if (point.tide.trend === 'BEARISH') {
      bearish += 1
    } else {
      neutral += 1
    }
  }
  return { bullish, bearish, neutral }
}

export const tideRegionHelp = {
  metricLabel: 'Tide Background (Screen 1 history)',
  definition:
    'The chart\'s background is shaded green/red/amber behind the candlesticks for every historical trading day, by what Screen 1 (the Tide -- docs/Analyse.md §2) actually was on that day: green = Bullish (only BUY signals were ever considered), red = Bearish (only SELL), amber = Neutral (neither -- no directional Triple Screen setup was being evaluated at all).',
  elderContext:
    'Elder\'s rule is to never trade against the tide -- Screen 1 gates BUY/SELL before Screen 2 (Wave) or Screen 3 (Trigger) ever get a say, so a stretch of amber (or the "wrong" color for the direction you were watching) is exactly why a BUY or SELL might have barely fired for long periods, even with plenty of price movement on the chart. This is recomputed per historical bar from that bar\'s own calendar week of weekly data (`GET /api/stocks/{ticker}/indicators`, backend-indicator-history-tide-exposure) -- not held fixed at today\'s Tide reading -- so the shading reflects what was actually true on each day, not a single current snapshot painted across the whole history.',
  interpretValue(points: readonly IndicatorHistoryPoint[]): string {
    if (points.length === 0) {
      return 'Currently unavailable for this ticker.'
    }
    const { bullish, bearish, neutral } = countTideTrends(points)
    const total = points.length
    const pct = (count: number) => Math.round((count / total) * 100)
    const latestTrend = points[points.length - 1].tide.trend
    const latestLabel =
      latestTrend === 'BULLISH'
        ? 'Bullish (green)'
        : latestTrend === 'BEARISH'
          ? 'Bearish (red)'
          : 'Neutral (amber)'
    return `Across the ${total} bars currently shown: ${pct(bullish)}% Bullish, ${pct(bearish)}% Bearish, ${pct(neutral)}% Neutral. Today's (rightmost) background is ${latestLabel}.`
  },
}
