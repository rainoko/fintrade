import type { Screens } from '../../../api/stocks'
import { humanizeSnakeCase } from '../../../utils/format'

export type SignalConditionKey = 'tide' | 'impulse' | 'wave' | 'trigger'

export interface SignalConditionExplanation {
  key: SignalConditionKey
  label: string
  /**
   * `true`/`false` when this ticker's currently-exposed screen values fully
   * determine whether the condition held; `null` only for the Wave
   * condition, and only when it's genuinely undeterminable from what
   * `GET /api/stocks/{ticker}/analysis` exposes today -- see this module's
   * own top-level docstring.
   */
  met: boolean | null
  detail: string
}

export interface SignalExplanation {
  headline: string
  conditions: SignalConditionExplanation[]
}

type Direction = 'BULLISH' | 'BEARISH'

/**
 * Builds a per-condition, per-ticker explanation of a BUY/SELL/HOLD signal
 * from `_determine_signal`'s four gates (backend/app/signals/engine.py,
 * docs/Analyse.md §5): Tide direction, the Impulse gate, Wave shows/showed
 * a qualifying pullback/rally, and Trigger fired. Pure/presentation-free so
 * it's independently unit-testable (colocated with, but split out of,
 * SignalSummary.tsx, same convention as ConfidenceGauge/confidenceBand.ts --
 * react-refresh/only-export-components).
 *
 * ## The Wave lookback data-availability gap (frontend-signal-why-explanation
 * task `decisions` entry)
 *
 * `_determine_signal` doesn't test today's Wave state directly -- it tests
 * `wave_showed_pullback`/`wave_showed_rally` (`_wave_lookback`), true if the
 * qualifying state appeared on *any* of the last 5 trading days, not just
 * today. `GET /api/stocks/{ticker}/analysis`'s `screens.wave.state` only
 * ever reports *today's* `evaluate_wave` result, so this module cannot
 * always know the Wave condition's true multi-day state -- only in these
 * cases can it be reconstructed exactly from what's exposed today:
 *
 * - **BUY/SELL**: the signal already proves `wave_showed_pullback`/`_rally`
 *   was true (that's one of `_determine_signal`'s four required conditions),
 *   so `met` is always `true`, with the detail noting whether today's own
 *   reading matches or the pullback/rally must have happened on an earlier
 *   day within the window.
 * - **HOLD, with Tide/Impulse/Trigger all otherwise satisfying the signal
 *   Tide's own direction**: if those three held today and the signal still
 *   came back HOLD, Wave must be the reason (by elimination -- if Wave had
 *   also shown/showed the qualifying state, `_determine_signal` would have
 *   returned BUY/SELL instead) -- so `met` is definitively `false`.
 * - **Every other HOLD case** (Tide Neutral, or Tide directional but Impulse
 *   already blocks or Trigger hasn't fired): today's `screens.wave.state`
 *   alone can't distinguish "the pullback/rally never happened in the last
 *   5 sessions" from "it happened on an earlier day this field doesn't
 *   show" -- `met` is `null` and the detail says so explicitly rather than
 *   guessing, alongside noting the *other* condition(s) that already block
 *   the signal regardless of Wave's true state.
 *
 * Extending the API to also expose `wave_showed_pullback`/`wave_showed_rally`
 * (or equivalent) would close this gap entirely -- filed as its own backend
 * task, `api-stocks-analysis-wave-lookback` (add-api-endpoint skill), rather
 * than folded into this frontend-skill task per the api-watchlist/
 * api-stocks-indicator-history precedent of a dedicated backend task for a
 * schema change. Until that lands, this module's `null` case is the honest
 * frontend-only fallback -- see this task's `decisions` entry.
 */
export function explainSignal(
  signal: 'BUY' | 'SELL' | 'HOLD',
  screens: Screens,
): SignalExplanation {
  const tideTrend = screens.tide.trend
  const impulse = screens.impulse
  const waveState = screens.wave.state
  const triggerFired = screens.trigger.fired
  const triggerReferenceLabel = humanizeSnakeCase(screens.trigger.reference)

  const direction: Direction | null =
    signal === 'BUY'
      ? 'BULLISH'
      : signal === 'SELL'
        ? 'BEARISH'
        : tideTrend === 'BULLISH'
          ? 'BULLISH'
          : tideTrend === 'BEARISH'
            ? 'BEARISH'
            : null

  if (direction === null) {
    const conditions: SignalConditionExplanation[] = [
      {
        key: 'tide',
        label: 'Tide direction (Screen 1)',
        met: false,
        detail:
          'Tide is Neutral -- the weekly MACD-Histogram slope and the 13/26-week EMA relationship disagree, so Screen 1 doesn’t support either a fresh BUY or a fresh SELL right now (docs/Analyse.md §2).',
      },
      {
        key: 'impulse',
        label: 'Impulse gate',
        met: null,
        detail: `Not evaluated -- the Impulse gate (currently ${impulse}) only matters once Tide picks a direction.`,
      },
      {
        key: 'wave',
        label: 'Wave pullback/rally (Screen 2)',
        met: null,
        detail: 'Not evaluated -- Wave is read against the Tide direction, and Tide is Neutral.',
      },
      {
        key: 'trigger',
        label: 'Trigger fired (Screen 3)',
        met: null,
        detail: 'Not evaluated -- Trigger confirms a resumption of the Tide direction, and Tide is Neutral.',
      },
    ]
    return {
      headline:
        'HOLD: Tide is Neutral, so no directional Triple Screen setup is being evaluated for this ticker right now.',
      conditions,
    }
  }

  const isBuySide = direction === 'BULLISH'
  const actionWord = isBuySide ? 'BUY' : 'SELL'
  const targetWaveState = isBuySide ? 'OVERSOLD_PULLBACK' : 'OVERBOUGHT_RALLY'
  const targetWaveLabel = isBuySide ? 'oversold pullback' : 'overbought rally'
  const blockingImpulseColor = isBuySide ? 'RED' : 'GREEN'

  // `direction` (above) is derived directly from `tideTrend` for a HOLD, and
  // is fixed to the matching direction for a BUY/SELL by the backend's own
  // invariant (`_determine_signal` only ever returns BUY when tide ==
  // "BULLISH", SELL when tide == "BEARISH") -- so Tide is unconditionally
  // "met" by construction on every path that reaches this point; there's no
  // real (reachable) case where `tideTrend !== direction` here to explain.
  const impulseMet = impulse !== blockingImpulseColor
  const triggerMet = triggerFired

  const tideCondition: SignalConditionExplanation = {
    key: 'tide',
    label: 'Tide direction (Screen 1)',
    met: true,
    detail: `Tide is ${humanizeSnakeCase(tideTrend)} -- the long-term weekly trend supports a ${actionWord}.`,
  }

  const impulseCondition: SignalConditionExplanation = {
    key: 'impulse',
    label: 'Impulse gate',
    met: impulseMet,
    detail: impulseMet
      ? `Impulse is ${impulse} -- it doesn’t block a fresh ${actionWord} (only ${blockingImpulseColor} would, docs/Analyse.md §3).`
      : `Impulse is ${impulse} -- this blocks any fresh ${actionWord} signal regardless of the other screens (docs/Analyse.md §3).`,
  }

  // `evaluate_trigger` (backend/app/signals/triple_screen.py) returns
  // `reference: "not_applicable"` not only when Tide is Neutral (handled
  // above, before `direction` is even resolved) but also whenever there are
  // fewer than 2 daily bars to compare -- reachable even with a directional
  // Tide derived from weekly data (e.g. a very new ticker). Rendering the
  // normal "reference: Not applicable" alongside a directional "hasn't
  // closed back above/below..." claim would be self-contradictory in that
  // case, so it gets its own wording instead (frontend-signal-why-
  // explanation-followups task `decisions` entry).
  const triggerReferenceUnavailable = screens.trigger.reference === 'not_applicable'

  const triggerCondition: SignalConditionExplanation = {
    key: 'trigger',
    label: 'Trigger fired (Screen 3)',
    met: triggerMet,
    detail: triggerMet
      ? `Trigger fired -- ${triggerReferenceLabel} (docs/Analyse.md §2 Screen 3).`
      : triggerReferenceUnavailable
        ? `Trigger hasn’t fired yet -- there isn’t enough daily price history yet to compare today’s close against a prior ${isBuySide ? 'high' : 'low'}.`
        : `Trigger hasn’t fired yet -- price hasn’t ${isBuySide ? 'closed back above the prior high' : 'closed back below the prior low'} (reference: ${triggerReferenceLabel}).`,
  }

  const waveMetToday = waveState === targetWaveState
  let waveCondition: SignalConditionExplanation
  if (waveMetToday) {
    waveCondition = {
      key: 'wave',
      label: 'Wave pullback/rally (Screen 2)',
      met: true,
      detail: `Wave shows an ${targetWaveLabel} today (Stochastic %K/Force Index confirm, docs/Analyse.md §2).`,
    }
  } else if (signal !== 'HOLD') {
    // BUY/SELL already proves wave_showed_pullback/_rally was true at some
    // point in the 5-day lookback, even though today's own reading doesn't
    // show it -- docs/Analyse.md §5 explicitly allows the pullback/rally to
    // have already ended by the day Trigger fires.
    waveCondition = {
      key: 'wave',
      label: 'Wave pullback/rally (Screen 2)',
      met: true,
      detail: `Wave doesn’t show an ${targetWaveLabel} today, but showed one within the last few trading days -- docs/Analyse.md §5 allows the pullback/rally to have already ended by the day Trigger actually fires.`,
    }
  } else if (impulseMet && triggerMet) {
    // Every other condition is satisfied today; if Wave had also shown/showed
    // the qualifying state within its 5-day lookback, this would be a fresh
    // BUY/SELL instead of a HOLD -- so by elimination, it didn't.
    waveCondition = {
      key: 'wave',
      label: 'Wave pullback/rally (Screen 2)',
      met: false,
      detail: `Wave has not shown a qualifying ${targetWaveLabel} in the last 5 trading days -- this is what’s currently blocking a fresh ${actionWord} (today’s Wave state: ${humanizeSnakeCase(waveState)}).`,
    }
  } else {
    // Genuinely ambiguous from what's exposed today: some other condition
    // already blocks the signal, so we can't tell whether Wave's 5-day
    // lookback separately would have qualified or not -- see this module's
    // own docstring.
    const otherBlockers = [
      !impulseMet ? 'the Impulse gate' : null,
      !triggerMet ? 'Trigger' : null,
    ].filter((label): label is string => label !== null)
    // `otherBlockers` is 1 or 2 items long here (see the branch condition
    // above); pick a subject-verb-agreeing verb rather than always the
    // singular "isn't", which reads wrong once both are joined with "and".
    const otherBlockersVerb = otherBlockers.length > 1 ? 'aren’t' : 'isn’t'
    waveCondition = {
      key: 'wave',
      label: 'Wave pullback/rally (Screen 2)',
      met: null,
      detail: `Today’s Wave state is ${humanizeSnakeCase(waveState)}, not a qualifying ${targetWaveLabel}. Wave looks back up to 5 trading days, so it may have shown one on an earlier day this view doesn’t show -- but ${otherBlockers.join(' and ')} also ${otherBlockersVerb} met, so this would be a HOLD either way.`,
    }
  }

  const conditions = [tideCondition, impulseCondition, waveCondition, triggerCondition]

  let headline: string
  if (signal !== 'HOLD') {
    headline = `${signal}: every Triple Screen condition lined up -- Tide ${humanizeSnakeCase(tideTrend)}, Impulse not blocking, Wave showed a${isBuySide ? 'n' : ''} ${targetWaveLabel}, and Trigger confirmed the resumption.`
  } else {
    // A HOLD reaching this point always has at least one condition with
    // met === false: `tideCondition.met` is always true here (`direction`
    // was itself derived from `tideTrend`, so they can't disagree), and
    // Wave's `met: null` (ambiguous) case only ever occurs when
    // `otherBlockers` -- Impulse and/or Trigger -- is non-empty, i.e. at
    // least one of those is already `false`. So `unmetLabels` below is
    // never empty for a HOLD -- see signalExplanation.test.ts.
    const unmetLabels = conditions.filter((c) => c.met === false).map((c) => c.label)
    headline = `HOLD: the ${humanizeSnakeCase(direction)} Tide setup isn’t complete for this ticker -- missing: ${unmetLabels.join(', ')}.`
  }

  return { headline, conditions }
}
