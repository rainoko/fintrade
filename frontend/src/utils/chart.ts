import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type SeriesType,
  type Time,
} from 'lightweight-charts'

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

/**
 * Moves `series` to the very end of its pane's render-order stack -- i.e.
 * always paints last (on top of every other series currently in that pane)
 * -- rather than a hardcoded numeric `setSeriesOrder` index.
 *
 * `PriceChart.tsx` keeps its candlestick series pinned above every
 * translucent/opaque fill series it draws on the same pane (the value-zone
 * `AreaSeries` fill/mask pair, frontend-channel-overlay; the support/
 * resistance zone `BaselineSeries` bands, frontend-support-resistance-
 * overlay) so a candle wick/body dipping into a shaded band is never
 * painted over -- Lightweight Charts otherwise draws a later-added series
 * above an earlier one on the same pane, which is exactly the bug PR #151
 * fixed (an opaque value-zone mask series painting over candlesticks below
 * it).
 *
 * A fixed literal index (that original fix's `series.setSeriesOrder(2)`)
 * only stays correct as long as exactly one effect ever adds fill series to
 * the pane. Once a second, independently re-running effect (the support/
 * resistance zone bands) also adds its own fill series to the same pane,
 * whichever effect happens to run last would overwrite the other's
 * hardcoded index with a now-stale absolute position, silently
 * reintroducing the same occlusion bug for whichever fill series the
 * *other* effect added. Recomputing "how many series are in this pane right
 * now" via `chart.panes()[paneIndex].getSeries().length` at the moment each
 * effect finishes adding its own series, instead, is self-healing
 * regardless of add/run order between them: whichever effect runs last
 * always ends by moving the candlestick series past everything currently in
 * the pane, including series the other effect added.
 */
export function bringSeriesToFront(
  chart: IChartApi,
  series: ISeriesApi<SeriesType>,
  paneIndex = 0,
): void {
  const paneSeriesCount = chart.panes()[paneIndex].getSeries().length
  series.setSeriesOrder(paneSeriesCount - 1)
}

/**
 * Converts a Lightweight Charts `Time` value back into the plain
 * `'YYYY-MM-DD'` string this app always feeds *in* (every series-building
 * helper under `features/stocks/components/` casts a backend `date` field
 * straight to `Time` via `as Time`, e.g. `PriceChart.tsx`'s
 * `buildOverlayData`). Needed because the library doesn't hand that string
 * back out unchanged: any event that reports a `Time` (e.g.
 * `chart.subscribeClick`'s `MouseEventParams.time`, used by the divergence-
 * marker click handling in `PriceChart.tsx`/`OscillatorChart.tsx`,
 * frontend-divergence-markers) normalizes a plain date string into a
 * `BusinessDay` object (`{ year, month, day }`) internally, so comparing a
 * clicked `Time` against an original date string requires converting one
 * side or the other first -- this is that conversion, in the
 * `BusinessDay`-\>string direction, so callers can compare against the
 * original API date strings directly.
 *
 * Domain-agnostic (Frontend.md §3's utils/-vs-features placement test, same
 * rationale `isFiniteNumber`/`createBaseChart` above already document) --
 * handles all three shapes `Time` can take, even though this app has never
 * fed the library a raw `UTCTimestamp` number itself, for completeness
 * against whatever shape a given event actually reports back.
 */
export function timeToDateString(time: Time): string {
  if (typeof time === 'string') {
    return time
  }
  if (typeof time === 'number') {
    return new Date(time * 1000).toISOString().slice(0, 10)
  }
  const { year, month, day } = time
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}
