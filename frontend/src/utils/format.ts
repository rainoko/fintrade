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
//
// `formatCurrency` below was added later (frontend-portfolio-risk-panel-
// followups.json) to consolidate a third case of the same pattern: three
// independent USD formatters on the Portfolio page alone (RiskPanel.tsx's
// and PositionsTable.tsx's identical `$${value.toFixed(2)}`, and
// PortfolioPage.tsx's richer `toLocaleString(..., {style:'currency'})` for
// its equity stat cards, which additionally applies thousands separators).
// The richer `toLocaleString` version was kept as the one canonical
// implementation — correct thousands-separator formatting is strictly
// better for a finance app's currency display, never worse, so there was no
// reason to standardize on the plainer of the two — see this task's
// `decisions` entry.
//
// `formatNullableCurrency` below was added later still
// (frontend-dashboard-page-followups.json) to finish that consolidation:
// DashboardPage.tsx had its own copy-pasted `formatCurrency`, and
// PositionsGlanceTable.tsx had its own independent nullable-price formatter
// (`value === null/undefined ? '—' : \`$${value.toFixed(2)}\``) that
// duplicated the null-check PositionsTable.tsx already applied on top of
// `formatCurrency`. Both are now the same one helper below rather than two
// independent 'render a nullable price' implementations that could silently
// drift apart — see this task's `decisions` entry. Note that this is not a
// no-op for PositionsGlanceTable.tsx specifically: unlike PositionsTable.tsx
// (already wrapping the shared `formatCurrency`) and DashboardPage.tsx
// (already using `toLocaleString`), PositionsGlanceTable.tsx's own prior
// `$${value.toFixed(2)}` never applied thousands separators, so any position
// priced at $1,000+ now renders e.g. `$1,234.50` instead of the old
// `$1234.50` — an intentional output change per the same "richer formatting
// is strictly better" rationale above, not a bug (see
// frontend-dashboard-page-followups-followups.json's `decisions` entry,
// which also adds the >=$1,000 regression-test fixture this consolidation
// was previously missing).

/**
 * Humanizes a snake_case domain value (e.g. an Elder Triple Screen field or
 * a confidence_breakdown component name) into a readable label: an explicit
 * `labelMap` entry wins when present (for values that need bespoke wording,
 * e.g. "2% rule breached" rather than "Two percent rule breached"), and any
 * other value falls back to underscores-to-spaces plus capitalizing the
 * first letter.
 */
export function humanizeSnakeCase(
  value: string,
  labelMap?: Record<string, string>,
): string {
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

/**
 * Formats a plain number as USD currency with thousands separators (e.g.
 * `1234.5` -> `"$1,234.50"`), for values assumed to always be present (cash,
 * cost basis, protective stop, ...). Callers with a nullable price (e.g.
 * `current_price`, which is null when a price fetch failed per API.md) wrap
 * this rather than duplicating it, the same convention `formatNullableNumber`
 * above establishes for numbers.
 *
 * The locale is pinned to `'en-US'` rather than passed as `undefined`
 * (which `formatNullableNumber` above still does): this is a USD-only
 * formatter (a hardcoded `currency: 'USD'`), so leaving the locale to
 * resolve from the runtime's default would make the grouping/decimal
 * separators and currency-symbol placement depend on whatever locale the
 * Node/browser environment happens to default to — deterministic today
 * only because the dev-container/CI image's default resolves to en-US, but
 * not guaranteed to stay that way across a future CI image or Node/ICU
 * upgrade, and not something real users' browsers are guaranteed to match
 * either. Pinning it makes both the production output and this file's unit
 * tests deterministic regardless of runtime locale (see
 * frontend-portfolio-risk-panel-followups-followups-followups.json).
 */
export function formatCurrency(value: number): string {
  return value.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

/**
 * Formats a nullable price via `formatCurrency`, rendering '—' for
 * `null`/`undefined` instead — the same "null means unknown, not zero"
 * convention `formatNullableNumber` establishes for plain numbers. For
 * fields like `current_price`, which is null when a price fetch failed
 * (docs/architecture/API.md).
 */
export function formatNullableCurrency(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : formatCurrency(value)
}

/**
 * Formats an ISO date or date-time string (e.g. `WatchlistItemOut.added_at`,
 * `"2026-09-18T14:03:00Z"`) as a short human-readable date (`"Sep 18, 2026"`),
 * dropping the time-of-day component since no current caller needs
 * sub-day precision. Domain-agnostic (any ISO date/date-time string) and not
 * a component, so it lives here rather than under `components/common/` or a
 * `features/<domain>/` folder, same placement rule as every other helper in
 * this file (Frontend.md §3). Locale is pinned to `'en-US'` for the same
 * determinism reason `formatCurrency` above pins it; `timeZone: 'UTC'` is
 * pinned too so a date-only input (parsed by `Date` as UTC midnight, e.g.
 * `entry_date`-style `"2026-01-05"`) always renders as that same calendar
 * date regardless of the host's local timezone offset, rather than
 * potentially shifting a day backward for a negative-offset timezone.
 */
export function formatDate(value: string): string {
  return new Date(value).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  })
}
