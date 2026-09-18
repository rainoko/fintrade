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
