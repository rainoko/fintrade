import { useEffect, type DependencyList } from 'react'

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
