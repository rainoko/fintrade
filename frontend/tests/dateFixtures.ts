/**
 * Shared date-fixture helper for tests that need to land a date a fixed number of weeks in
 * the past relative to "now" -- used by both the MSW mock handlers (`tests/mocks/handlers.ts`,
 * vitest) and the Playwright e2e specs (`tests/e2e/portfolio.spec.ts`) to seed closed-trade
 * fixtures inside the backend's 8-10-week follow-up-due window (API.md's `due_for_follow_up`
 * query parameter, `app.api.routers.portfolio`'s `_FOLLOW_UP_DUE_WINDOW_MIN`/`_MAX`). Lives at
 * `tests/` root (rather than under `tests/mocks/` or `tests/e2e/`) since both `tsconfig.app.json`
 * and vitest's config include the whole `tests` directory, and neither test layer's own
 * subdirectory is a natural home for something the other also needs.
 */
export function isoDateWeeksAgo(weeks: number): string {
  const date = new Date()
  date.setUTCDate(date.getUTCDate() - weeks * 7)
  return date.toISOString().slice(0, 10)
}
