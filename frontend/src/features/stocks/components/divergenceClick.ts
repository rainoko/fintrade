import type { MouseEventParams, Time } from 'lightweight-charts'
import type { DivergenceOut } from '../../../api/stocks'
import { timeToDateString } from '../../../utils/chart'

/**
 * `true` when a chart click's own `MouseEventParams.time` lands on one of
 * `divergence`'s two extreme dates -- the "clicked a divergence marker"
 * test both `PriceChart.tsx`'s and `OscillatorChart.tsx`'s
 * `chart.subscribeClick` handlers use (frontend-divergence-markers). The
 * one genuinely shared piece of divergence-click logic between the two
 * charts -- unlike each chart's own line/marker-building helpers (kept
 * local per component, same convention `buildOverlayData`/
 * `buildOscillatorSeriesData` already establish for conceptually-similar
 * but shape-specific series builders), the "did this click land on either
 * extreme date" test is identical regardless of which chart/pane it's
 * checked against, so it's colocated here rather than duplicated.
 *
 * Compares by date string (`timeToDateString`, `utils/chart.ts`) rather
 * than the raw `Time` value, since a clicked `Time` comes back as a
 * `BusinessDay` object even though this app always feeds the library a
 * plain `'YYYY-MM-DD'` string -- see that helper's own doc comment.
 */
export function clickedDivergenceExtreme(
  divergence: DivergenceOut,
  param: MouseEventParams<Time>,
): boolean {
  if (!param.time) {
    return false
  }
  const clickedDate = timeToDateString(param.time)
  return (
    clickedDate === divergence.first_extreme_date ||
    clickedDate === divergence.second_extreme_date
  )
}
