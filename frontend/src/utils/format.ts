// Shared, domain-agnostic string/number display helpers. Lives under
// `src/utils/` (a new top-level folder, sibling to `api/`/`components/`/
// `features/`) rather than under any single `features/<domain>/` folder or
// `components/common/`: both helpers below operate on any snake_case string
// or any nullable number and don't know what a "signal", "position", or
// "screen" is (Frontend.md §3's placement test — a component/helper belongs
// under `features/<domain>/` only if it references that domain's concepts),
// so they're genuinely cross-feature, not stock- or portfolio-specific. They
// also aren't React components (no props, no rendering, no Storybook
// story), so `components/common/` — which Frontend.md §3/§4 define as the
// catalog of reusable *components*, each with a story — isn't the right
// home either; see this task's `decisions` entry
// (frontend-stock-analysis-page-followups.json) for the full reasoning.
//
// Consolidates what were three independent label-map-plus-fallback
// implementations (SignalSummary.tsx's humanizeComponent, ScreensPanel.tsx's
// humanize, RiskPanel.tsx's humanizeFlag) and two independent null-safe
// number formatters (IndicatorsPanel.tsx's formatValue, ScreensPanel.tsx's
// formatNullableNumber) into one implementation each.

/**
 * Humanizes a snake_case domain value (e.g. an Elder Triple Screen field or
 * a confidence_breakdown component name) into a readable label: an explicit
 * `labelMap` entry wins when present (for values that need bespoke wording,
 * e.g. "2% rule breached" rather than "Two percent rule breached"), and any
 * other value falls back to underscores-to-spaces plus capitalizing the
 * first letter.
 */
export function humanizeSnakeCase(value: string, labelMap?: Record<string, string>): string {
  const known = labelMap?.[value]
  if (known) {
    return known
  }
  const words = value.replace(/_/g, ' ').toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/**
 * Formats a number for display, rendering '—' for `null`/`undefined`/`NaN`
 * instead of calling `.toLocaleString()` on a non-number. Several
 * `AnalysisResponse` fields (`indicators.*`, `screens.wave.stochastic_k`/
 * `force_index_2ema`) are typed as non-optional `number` in the generated
 * client. `docs/tasks/api-stocks-analysis-nullable-indicators.json` fixed the
 * backend-side root cause (an unsettled latest daily bar with NaN OHLC is now
 * excluded from analysis via `app.signals.engine.drop_malformed_daily_bars`
 * rather than leaking a JSON `null` onto the wire), so this guard shouldn't be
 * reachable against a real backend response anymore — kept as defense-in-depth
 * (treating the generated type as optimistic, not a runtime guarantee) rather
 * than removed, the same convention PositionsTable.tsx's/
 * PositionsGlanceTable.tsx's `formatNullableCurrency` apply to nullable
 * prices.
 */
export function formatNullableNumber(
  value: number | null | undefined,
  options?: Intl.NumberFormatOptions,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '—'
  }
  return value.toLocaleString(undefined, options)
}
