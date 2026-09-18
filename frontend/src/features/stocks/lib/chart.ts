import { createChart, type IChartApi } from 'lightweight-charts'

/**
 * Shared base `createChart` options for every Lightweight Charts instance
 * under features/stocks/components/ (`PriceChart`'s candlestick chart,
 * `OscillatorChart`'s three-pane oscillator chart) — a single source for
 * options that must stay identical across both (`autoSize` so the chart
 * fills its container, a transparent layout background so the MUI theme's
 * own surface shows through), so the two chart-creation call sites can't
 * silently drift apart the way two independently hand-maintained
 * `createChart(container, {...})` literals could. See
 * frontend-oscillator-chart-followups.
 */
export function createBaseChart(container: HTMLElement): IChartApi {
  return createChart(container, {
    autoSize: true,
    layout: { background: { color: 'transparent' } },
  })
}
