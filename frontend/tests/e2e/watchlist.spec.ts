import { expect, test, type Page } from '@playwright/test'

// A fixture ticker (see backend/app/data/fixture_provider.py) distinct from the ones the
// other e2e specs use (AAPL: navigation/stock-analysis; MSFT: portfolio), so this spec's
// add/remove cycle can't be confused with state either of those leave behind.
const TICKER = 'GOOGL'

function watchlistRow(page: Page) {
  return page
    .getByRole('table', { name: 'Watchlist' })
    .getByRole('row', { name: new RegExp(`^${TICKER}\\b`) })
}

/**
 * Watchlist page (pages/WatchlistPage.tsx): view watched tickers, add one through the inline
 * AddTickerForm, see it appear in the table with its signal badge, then remove it through the
 * confirm dialog — the same golden-path shape dashboard.spec.ts/navigation.spec.ts/
 * portfolio.spec.ts/stock-analysis.spec.ts already cover for the other top-level nav
 * destinations (frontend-watchlist-page-followups, tracking the gap PR #106's review found).
 * A single `test.describe.serial` block (add depends on the page state the previous step left
 * behind) rather than one big test, so a failure midway reports exactly which step broke —
 * same structure portfolio.spec.ts uses.
 *
 * Self-cleaning by design (the last step removes what the first step added) and tolerant of a
 * pre-existing GOOGL watchlist entry from an earlier interrupted run (POST /api/watchlist is an
 * idempotent no-op on a duplicate add, API.md) — both matter because playwright.config.ts's
 * webServer only guarantees a clean database at the start of a whole `yarn test:e2e`
 * invocation, not before each individual spec file.
 */
test.describe.serial('watchlist: view, add, and remove a ticker', () => {
  test('watchlist page loads with a watchlist table', async ({ page }) => {
    await page.goto('/watchlist')
    await expect(page.getByRole('heading', { level: 1, name: 'Watchlist' })).toBeVisible()

    const watchlistTable = page.getByRole('table', { name: 'Watchlist' })
    const emptyState = page.getByText(
      'Your watchlist is empty. Add a ticker to get started.',
    )
    await expect(watchlistTable.or(emptyState)).toBeVisible()
  })

  test('adding a ticker shows it in the watchlist table with a signal badge', async ({
    page,
  }) => {
    await page.goto('/watchlist')

    await page.getByLabel('Add ticker to watchlist').fill(TICKER)
    await page.getByRole('button', { name: 'Add' }).click()

    await expect(watchlistRow(page)).toBeVisible()
    // Signal is computed against the real (fixture-backed) backend, so only its structural
    // shape is asserted -- same reasoning stock-analysis.spec.ts uses for AAPL's own
    // non-engineered fixture series: a BUY/SELL/HOLD badge renders, not a specific outcome.
    await expect(watchlistRow(page).getByTestId('signal-badge')).toHaveText(
      /^(BUY|SELL|HOLD)$/,
    )
  })

  test('removing the ticker takes it out of the table', async ({ page }) => {
    await page.goto('/watchlist')

    await watchlistRow(page)
      .getByRole('button', { name: `Remove ${TICKER}` })
      .click()

    const confirmDialog = page.getByRole('dialog', { name: 'Remove from watchlist' })
    await expect(confirmDialog).toBeVisible()
    await confirmDialog.getByRole('button', { name: 'Remove' }).click()
    await expect(confirmDialog).not.toBeVisible()

    await expect(watchlistRow(page)).toHaveCount(0)
  })
})

// Regression check for MarketBreadthCard (frontend-market-breadth-widget-followups): the e2e
// stack always runs with IBKR disabled (backend/app/config.py's `ibkr_enabled: bool = False`
// default -- playwright.config.ts's webServer never overrides it), so this card is guaranteed to
// always render its disabled/unavailable panel here, never the real advance/decline data -- a
// stable, deterministic thing to assert as a persisted e2e check, unlike the "available" state
// (which would need a stub IBKR gateway this suite doesn't run). Kept outside the
// `describe.serial` block above since it neither depends on nor mutates the add/remove flow's
// watchlist state -- a failure here shouldn't skip that flow's remaining steps, or vice versa.
// No equivalent e2e assertion exists yet for PersonalBreadthCard either (see this task's
// `decisions` entry) -- this follows this spec file's own existing assertion style rather than a
// PersonalBreadthCard e2e pattern.
test('market breadth card shows the disabled panel when IBKR is not connected', async ({
  page,
}) => {
  await page.goto('/watchlist')

  // Scoped to `main` since the app shell's own header IbkrStatusIndicator (AppShell.tsx)
  // renders the same "IBKR: Disabled" chip text outside this card -- a plain page-wide
  // `getByText` would match both and fail Playwright's strict-mode uniqueness check.
  const main = page.getByRole('main')
  await expect(
    main.getByRole('heading', { level: 2, name: 'Market Breadth (IBKR, Whole Market)' }),
  ).toBeVisible()
  await expect(
    main.getByText(
      "Real market breadth isn't available right now — it needs the optional IBKR Client Portal Gateway integration connected.",
    ),
  ).toBeVisible()
  await expect(main.getByText('IBKR: Disabled')).toBeVisible()
})
