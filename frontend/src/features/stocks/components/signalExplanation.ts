import type { Screens } from '../../../api/stocks'
import { humanizeSnakeCase } from '../../../utils/format'
import { TIDE_INSUFFICIENT_HISTORY_OR_FLAT_SLOPE_HEDGE } from './tideNeutralCause'

export type SignalConditionKey = 'tide' | 'impulse' | 'wave' | 'trigger'

export interface SignalConditionExplanation {
  key: SignalConditionKey
  label: string
  /**
   * `true`/`false` whenever this ticker's currently-exposed screen values
   * determine whether the condition held; `null` only for the Impulse,
   * Wave, and Trigger conditions, and only when Tide itself is Neutral --
   * those three screens are evaluated against a Tide direction that
   * doesn't exist in that case, so "not evaluated" is the accurate state,
   * not a data-availability gap. Once Tide picks a direction, every
   * condition (including Wave, since `showed_pullback_in_lookback`/
   * `showed_rally_in_lookback` on `GET /api/stocks/{ticker}/analysis`
   * expose the real 5-day lookback result `_determine_signal` gates on)
   * resolves to a definite `true`/`false` -- see this module's own
   * top-level docstring.
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
 * ## Wave's condition reads the 5-day lookback, not just today's state
 * (resolved: frontend-signal-wave-lookback-explanation task)
 *
 * `_determine_signal` doesn't test today's Wave state directly -- it tests
 * `wave_showed_pullback`/`wave_showed_rally` (`_wave_lookback`), true if the
 * qualifying state appeared on *any* of the last 5 trading days, not just
 * today. `GET /api/stocks/{ticker}/analysis` exposes exactly those two
 * booleans as `screens.wave.showed_pullback_in_lookback`/
 * `showed_rally_in_lookback` (non-null whenever `screens.tide.trend` is
 * directional, `null` only when it's NEUTRAL -- see `WaveScreen`'s own
 * schema description), so this module reads the real lookback result
 * directly instead of reconstructing it from today's `screens.wave.state`
 * alone:
 *
 * - **BUY/SELL**: the signal already proves the relevant lookback boolean
 *   was `true` (one of `_determine_signal`'s four required conditions), so
 *   `met` is always `true`, with the detail noting whether today's own
 *   reading matches or the pullback/rally happened on an earlier day
 *   within the window.
 * - **HOLD, with Tide directional**: the lookback boolean is read directly
 *   and reported as-is -- `met: true` (today or an earlier day within the
 *   window) if some *other* condition (Impulse/Trigger) is what's blocking
 *   a fresh BUY/SELL, or `met: false` if Wave itself never showed the
 *   qualifying state in the window, whether or not another condition also
 *   blocks.
 * - **HOLD, with Tide Neutral**: Wave (and Impulse and Trigger) are never
 *   evaluated against a direction that doesn't exist, so `met` stays
 *   `null` -- this is "not evaluated", not "undeterminable" (see the
 *   Tide-Neutral early return below).
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
    // Screen 1 (Tide) is the weekly Impulse System color as of
    // `backend-weekly-impulse-screen1` -- `weekly_macd_histogram_slope`
    // (`weeklySlope` below) is purely informational now and no longer
    // decides `trend`, so `weeklySlope === 'flat'` here just means the
    // *informational* reading is ambiguous between two distinct causes
    // `evaluate_tide` (backend/app/signals/triple_screen.py) doesn't expose
    // separately: a genuinely small weekly MACD-Histogram step (with a real
    // weekly Impulse Blue behind it -- the EMA(13)/MACD-Histogram
    // bar-over-bar directions still disagreeing), or its <2-weekly-bar
    // short-circuit where no weekly Impulse color is computed at all.
    // `TideScreen` doesn't expose a weekly bar count, so naming both
    // possibilities (rather than asserting either) is the most this
    // frontend can honestly say -- same reasoning as
    // metricHelpContent.ts's tideHelp.interpretValue, mirrored here via the
    // shared TIDE_INSUFFICIENT_HISTORY_OR_FLAT_SLOPE_HEDGE constant so the
    // wording only needs fixing in one place going forward (see this task's
    // and frontend-stock-detail-metric-help-followups-followups's own
    // `decisions` entries).
    const weeklySlope = screens.tide.weekly_macd_histogram_slope
    const conditions: SignalConditionExplanation[] = [
      {
        key: 'tide',
        label: 'Tide direction (Screen 1)',
        met: false,
        detail:
          weeklySlope === 'flat'
            ? `Tide is Neutral -- ${TIDE_INSUFFICIENT_HISTORY_OR_FLAT_SLOPE_HEDGE} -- either way, Screen 1 doesn’t support either a fresh BUY or a fresh SELL right now (docs/Analyse.md §2).`
            : 'Tide is Neutral -- the weekly EMA(13) and weekly MACD-Histogram aren’t moving in the same direction, so the weekly Impulse System reads Blue, and Screen 1 doesn’t support either a fresh BUY or a fresh SELL right now (docs/Analyse.md §2, §3).',
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
        detail:
          'Not evaluated -- Wave is read against the Tide direction, and Tide is Neutral.',
      },
      {
        key: 'trigger',
        label: 'Trigger fired (Screen 3)',
        met: null,
        detail:
          'Not evaluated -- Trigger confirms a resumption of the Tide direction, and Tide is Neutral.',
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
  // Tide is directional here (the Neutral case already returned above), so
  // the relevant lookback boolean is never null -- see WaveScreen.
  // showed_pullback_in_lookback/showed_rally_in_lookback's own schema
  // description (null only when screens.tide.trend is NEUTRAL) and this
  // module's own top-level docstring. `?? false` is a defensive fallback
  // only, not an expected path.
  const waveShowedInLookback =
    (isBuySide
      ? screens.wave.showed_pullback_in_lookback
      : screens.wave.showed_rally_in_lookback) ?? false

  let waveCondition: SignalConditionExplanation
  if (waveMetToday) {
    waveCondition = {
      key: 'wave',
      label: 'Wave pullback/rally (Screen 2)',
      met: true,
      detail: `Wave shows an ${targetWaveLabel} today (Stochastic %K/Force Index confirm, docs/Analyse.md §2).`,
    }
  } else if (waveShowedInLookback) {
    // Today's own reading doesn't show it, but the 5-day lookback did on an
    // earlier day -- docs/Analyse.md §5 explicitly allows the pullback/rally
    // to have already ended by the day Trigger fires (or, for a HOLD, by
    // today).
    waveCondition = {
      key: 'wave',
      label: 'Wave pullback/rally (Screen 2)',
      met: true,
      detail: `Wave doesn’t show an ${targetWaveLabel} today, but showed one within the last 5 trading days -- docs/Analyse.md §5 allows the pullback/rally to have already ended by the day Trigger actually fires.`,
    }
  } else {
    // Wave never showed the qualifying state in its own 5-day lookback,
    // whether or not it's also the *only* thing currently blocking a fresh
    // BUY/SELL -- unreachable for signal !== 'HOLD', since a BUY/SELL
    // already proves this boolean was true.
    waveCondition = {
      key: 'wave',
      label: 'Wave pullback/rally (Screen 2)',
      met: false,
      detail: `Wave has not shown a qualifying ${targetWaveLabel} in the last 5 trading days (today’s Wave state: ${humanizeSnakeCase(waveState)}).`,
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
    // `_determine_signal` only returns BUY/SELL when Impulse, Wave, and
    // Trigger are *all* met -- so a HOLD with a directional Tide means at
    // least one of the other three is `false` here too. So `unmetLabels`
    // below is never empty for a HOLD -- see signalExplanation.test.ts.
    const unmetLabels = conditions.filter((c) => c.met === false).map((c) => c.label)
    headline = `HOLD: the ${humanizeSnakeCase(direction)} Tide setup isn’t complete for this ticker -- missing: ${unmetLabels.join(', ')}.`
  }

  return { headline, conditions }
}
