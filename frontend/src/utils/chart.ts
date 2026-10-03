import { useEffect, type DependencyList } from 'react'
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
 * Moves every series in `seriesGroup` to the top of its pane's render-order
 * stack, as a single contiguous block, while preserving each member's
 * position *relative to the other members of the group* — e.g. if
 * `seriesGroup` is `[a, b, c]`, the group ends up stacked `a` below `b`
 * below `c` (matching `seriesGroup`'s own order), directly beneath whatever
 * else calls `bringSeriesToFront` afterwards, regardless of where `a`/`b`/`c`
 * individually sat in the pane beforehand (mixed in with other series, in
 * any order).
 *
 * `PriceChart.tsx` uses this to re-assert the support/resistance zone
 * bands' (`BaselineSeries`, frontend-support-resistance-overlay) own z-order
 * whenever a later-resolving effect (the value-zone mask, the tide-region
 * shading) adds new fill series to the same pane after the zone bands were
 * already added — see `bringSeriesToFront`'s own doc comment for why that
 * reassertion is needed at all, and this function's own
 * frontend-support-zones-disappear-after-oscillators-followups `decisions`
 * entry for why more than one zone band could ever need reordering as a
 * group in the first place (more than one support/resistance zone
 * currently displayed at once).
 *
 * Implemented as `seriesGroup.length` sequential `bringSeriesToFront` calls,
 * in `seriesGroup`'s own order — deliberately NOT by computing each
 * member's target index up front (e.g. `paneSeriesCount - seriesGroup.length
 * + i`) and assigning it directly. That alternative looks equivalent but
 * isn't: `ISeriesApi.setSeriesOrder` splices its target series out of the
 * pane's source list and reinserts it at the given index immediately, before
 * the next call runs — so an index computed once, up front, against the
 * pre-move layout can land a later group member short of its intended slot
 * once an earlier already-moved member has shifted the tail of the list out
 * from under it (confirmed by hand-simulating both approaches against
 * Lightweight Charts' own bundled `Pane._internal_setSeriesOrder`
 * implementation — the same source PR #350's review verified
 * `bringSeriesToFront` itself against). Calling `bringSeriesToFront` once
 * per member instead sidesteps that entirely: each call always targets "the
 * very top of the pane, whatever that currently is", so a member processed
 * later always ends up above one processed earlier — which is exactly
 * `seriesGroup`'s own order, with no dependency on any member's position
 * before this function runs.
 */
export function bringSeriesGroupToFront(
  chart: IChartApi,
  seriesGroup: readonly ISeriesApi<SeriesType>[],
  paneIndex = 0,
): void {
  seriesGroup.forEach((series) => bringSeriesToFront(chart, series, paneIndex))
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

interface VisibilityToggleableSeries {
  applyOptions: (options: { visible: boolean }) => void
}

/**
 * Applies `visible` onto whichever series instance(s) `getSeries` currently
 * returns -- the repeated "ref onto the currently-drawn series + a small
 * dedicated effect applying `{ visible }`" pattern, independently hand-
 * written once per toggle across `PriceChart`/`OscillatorChart`/
 * `VolumeIndicatorsChart`/`TrendStrengthChart` (frontend-chart-legend-
 * toggle-overlay-followups).
 *
 * Lives here rather than `features/stocks/hooks/` (where
 * frontend-chart-legend-toggle-overlay-followups originally placed it)
 * despite being a hook, not a plain function, and despite every current
 * caller being under `features/stocks/` -- it's domain-agnostic (operates on
 * the generic `{ applyOptions }` shape above, with no reference to
 * ticker/position/signal) and chart-library-specific in exactly the way
 * `createBaseChart`/`isFiniteNumber`/`bringSeriesToFront` above already are,
 * which is this file's own established placement test (see each of their
 * doc comments). Frontend.md §3's "hooks live under the feature they serve"
 * rule is framed around *API-concern* hooks (`useQuery`/`useMutation`
 * wrappers like `useStockAnalysis`) so that a feature's data layer stays
 * next to the components using it -- this hook wraps no API concern at all,
 * so that rationale doesn't actually apply to it. Being a hook (using
 * `useEffect` internally) rather than a plain function isn't by itself a
 * reason to place it differently from this file's other series helpers:
 * nothing about React's hook rules (naming, call-site position) depends on
 * which directory the hook's definition file lives in, only on the
 * importing component itself following them -- see
 * frontend-chart-legend-toggle-overlay-followups-followups' `decisions`
 * entry for the fuller reasoning (including why this constitutes a genuine,
 * generalizable answer to the "is a domain-agnostic hook different enough
 * from a plain function to warrant a different placement rule" question
 * Frontend.md §3 previously left open, not just a one-off call for this
 * hook alone).
 *
 * `getSeries` is a thunk, not the ref(s) themselves, so this hook stays
 * agnostic to whatever shape each caller's own ref(s) take (a single
 * nullable ref, a nullable ref onto a fixed-size tuple, or a ref onto a
 * growing array) -- see each call site. Called fresh inside the effect (not
 * memoized/stored), so it always reads whatever the caller's own
 * series-drawing effect most recently populated its ref(s) with.
 *
 * `extraDeps` mirrors each call site's own series-drawing effect's
 * dependency list (the `/indicators`-or-`/history` query data, `theme`, an
 * `enabled`/`overlayEnabled` gate) -- deliberately a required, explicit
 * parameter rather than anything this hook guesses at, since that list
 * genuinely differs per call site. Re-running whenever any of those change
 * (not just `visible`) ensures a freshly recreated series immediately gets
 * the current toggle state re-applied instead of silently defaulting back
 * to visible -- see each original call site's own comment for why.
 */
export function useSeriesVisibilityToggle(
  getSeries: () => readonly (VisibilityToggleableSeries | null | undefined)[],
  visible: boolean,
  extraDeps: DependencyList,
): void {
  useEffect(() => {
    getSeries().forEach((series) => series?.applyOptions({ visible }))
    // `getSeries`/`visible` are covered explicitly; `extraDeps` is each
    // caller's own series-drawing effect's dependency list, passed through
    // verbatim -- see this hook's own doc comment for why it can't be
    // statically spelled out here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, ...extraDeps])
}
