import ButtonBase from '@mui/material/ButtonBase'
import type { ReactNode } from 'react'

/**
 * Shared "this legend row doesn't currently apply to what's on screen"
 * dimming opacity -- used here for a toggled-off overlay, and reused as-is by
 * `PriceChart.tsx`/`OscillatorChart.tsx` for their own non-toggle "out of
 * [the currently visible] range" legend rows (False Breakout/Divergence/
 * Kangaroo Tail -- see those components' own usage). Both are the same
 * affordance from a reader's point of view (a legend row that's present but
 * not currently reflected on the chart), so they share one constant rather
 * than two independently-chosen magic numbers that happened to read as
 * "about the same" (frontend-chart-legend-toggle-overlay-followups,
 * consolidating what was previously this component's own `0.45` against the
 * other three call sites' pre-existing `0.4`) -- `0.4`, the pre-existing
 * value, won out over `0.45` since three call sites already depended on it
 * and none of them are this task's to revisit, while this component's single
 * call site is.
 */
export const LEGEND_DIM_OPACITY = 0.4

export interface LegendToggleProps {
  /**
   * Whether the overlay this legend row describes is currently shown on the
   * chart. Purely presentational here (dims the whole row when `false`) --
   * the caller owns the actual on/off state and whatever hide/show mechanism
   * applies to its own series/price-line type (see
   * `frontend-chart-legend-toggle-overlay`'s `decisions` entry: a
   * `LineSeries`/`AreaSeries`/`BaselineSeries` toggles via
   * `series.applyOptions({ visible })`, while a Fibonacci-style price line
   * has no such option and is removed/recreated instead -- neither mechanism
   * belongs in this domain-agnostic wrapper).
   */
  active: boolean
  /** Human-readable name of the overlay, used to build this toggle's
   * accessible name ("Hide <label> on the chart" / "Show <label> on the
   * chart") -- distinct from the visible `children` content so the
   * accessible name reads naturally even when `children` is a swatch +
   * abbreviated caption (e.g. "+DI / -DI (13)"). */
  label: string
  /** Called on click or Enter/Space activation; the caller flips its own
   * `active` state (and applies the actual hide/show mechanism) in
   * response -- this component holds no state of its own. */
  onToggle: () => void
  /** The swatch + `Typography` caption content already built by each
   * caller's own legend row -- rendered as-is inside the clickable area.
   * Deliberately does NOT include a `MetricHelp` icon: every call site keeps
   * that as a sibling of this component within the same row, so the two
   * affordances can never intercept each other's clicks (there is no
   * nesting for a click to bubble through in the first place) -- see
   * `frontend-chart-legend-toggle-overlay`'s `decisions` entry for why
   * dimming (not `stopPropagation`) is the mechanism that keeps the two
   * affordances independent. */
  children: ReactNode
}

/**
 * Makes an existing chart-legend row's swatch + label clickable to toggle
 * that overlay's visibility on the chart next to it (Stock Detail's
 * `PriceChart`/`OscillatorChart`/`VolumeIndicatorsChart`/
 * `TrendStrengthChart`, `frontend-chart-legend-toggle-overlay`) --
 * domain-agnostic (`active`/`label`/`onToggle` carry no stocks/portfolio
 * concept), so it lives in `components/common/` per Frontend.md §3's
 * placement test, the same way `MetricHelp` itself does for the adjacent
 * "explain this metric" affordance.
 *
 * Renders a real `<button>` (MUI `ButtonBase`) around the caller's own
 * swatch/label content: native Enter/Space activation and focusability come
 * for free, `aria-pressed` reports the current on/off state the way a
 * toggle button should (see
 * https://www.w3.org/WAI/ARIA/apg/patterns/button/#toggle-button), and the
 * whole content is dimmed (`opacity`, chosen over a strikethrough -- see
 * this task's `decisions` entry) when `active` is `false`, so both the
 * swatch's color and the label's text read as "currently hidden" at a
 * glance without needing a second, separate visual signal for each.
 */
export default function LegendToggle({
  active,
  label,
  onToggle,
  children,
}: LegendToggleProps) {
  return (
    <ButtonBase
      onClick={onToggle}
      aria-pressed={active}
      aria-label={`${active ? 'Hide' : 'Show'} ${label} on the chart`}
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 0.5,
        borderRadius: 1,
        px: 0.5,
        py: 0.25,
        mx: -0.5,
        my: -0.25,
        opacity: active ? 1 : LEGEND_DIM_OPACITY,
      }}
    >
      {children}
    </ButtonBase>
  )
}
