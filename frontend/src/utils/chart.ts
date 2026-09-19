import { createChart, type IChartApi } from 'lightweight-charts'

/**
 * Shared base `createChart` options for every Lightweight Charts instance
 * under features/stocks/components/ (`PriceChart`'s candlestick chart,
 * `OscillatorChart`'s three-pane oscillator chart) — a single source for
 * options that must stay identical across both (`autoSize` so the chart
 * fills its container, a transparent layout background so the MUI theme's
 * own surface shows through), so the two chart-creation call sites can't
 * silently drift apart the way two independently hand-maintained
 * `createChart(container, {...})` literals could.
 *
 * Lives in `utils/`, not `features/stocks/lib/`, despite both of today's
 * callers being under `features/stocks/`: it takes a raw `HTMLElement` and
 * returns a generic `IChartApi`, with no reference to any stocks-domain
 * concept (ticker/position/signal), which is exactly Frontend.md §3's
 * utils/-vs-features placement test ("domain-agnostic and not a component ->
 * utils/") — the same test that places `format.ts` here despite it also
 * having started with a single consumer. See the
 * frontend-oscillator-chart-followups task's `decisions` entry.
 */
export function createBaseChart(container: HTMLElement): IChartApi {
  return createChart(container, {
    autoSize: true,
    layout: { background: { color: 'transparent' } },
  })
}

/**
 * `true` for a real, plottable numeric value -- `false` for `null`,
 * `undefined`, `NaN`, or anything non-numeric. Lightweight Charts' own
 * `setData`/series-point APIs throw synchronously on a non-finite value,
 * which -- uncaught -- crashes the whole app via the root
 * `AppErrorBoundary`, not just one chart pane, so every series-building
 * helper under `features/stocks/components/` guards each point with this
 * before pushing it, rather than trusting a generated type's optimistic
 * `number` (several OpenAPI fields here are honestly `number | null` for a
 * real warm-up-window reason -- e.g. `stochastic_k`/`force_index_2ema`/
 * `channel_upper`/`channel_lower` -- but even a field typed as plain
 * `number` isn't a runtime guarantee; see `PriceChart.tsx`'s own
 * `hasFiniteOhlc` for the same defense against a still-forming daily bar).
 *
 * Promoted here (rather than kept as a private helper duplicated in both
 * `OscillatorChart.tsx`, which needed it first, and `PriceChart.tsx`, which
 * needs the exact same guard for the new channel-band overlay) since it's
 * domain-agnostic -- Frontend.md §3's utils/-vs-features placement test,
 * same rationale `createBaseChart` above already documents for this file.
 */
export function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}
