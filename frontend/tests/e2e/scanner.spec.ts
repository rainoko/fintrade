import { expect, test, type Page } from '@playwright/test'

// A synthetic symbol used only by this spec's mocked scanner response (see
// `mockAvailableScanner` below) -- deliberately not one of
// backend/app/data/fixture_provider.py's four real fixture tickers (AAPL/MSFT/TSLA/GOOGL,
// already claimed by navigation/stock-analysis/portfolio/watchlist.spec.ts respectively),
// so this spec's own watchlist add/cleanup can never be confused with theirs.
// GET/DELETE /api/watchlist don't require a ticker to exist in FixtureDataProvider (adding
// one just inserts a row; that row's signal degrades to null on read, same as any other
// ticker FixtureDataProvider doesn't know about -- see backend/app/api/routers/
// watchlist.py's `_compute_signal`), so this is safe to add for real against the running
// e2e backend.
const SCAN_RESULT_TICKER = 'SCANE2E'

function scanResultRow(page: Page) {
  return page
    .getByRole('table', { name: 'Scanner results' })
    .getByRole('row', { name: new RegExp(`^${SCAN_RESULT_TICKER}\\b`) })
}

/**
 * Stubs `GET /api/ibkr/scanner/params` and `POST /api/ibkr/scanner/run` at the browser's
 * own network boundary so the golden path below can exercise an `'available'` scanner state
 * end to end through a real running frontend + backend.
 *
 * Unlike every other e2e spec in this suite (which always drives the real, unmocked
 * backend), this is unavoidable here: `playwright.config.ts`'s webServer never sets
 * `FINTRADE_IBKR_ENABLED`, so `GET /api/ibkr/scanner/params` always reports `state:
 * 'disabled'` in this stack (`app/config.py`'s `ibkr_enabled` defaults to `False`, and no
 * sandboxed/CI/dev-container environment has a live, interactively-logged-in IBKR gateway
 * to enable it against -- see `app/data/ibkr_provider.py`'s own module docstring, "no
 * sandboxed/CI environment has a live authenticated gateway to test against"). That's the
 * exact same constraint `IBKRProvider`'s own pytest suite already works around by mocking
 * HTTP at the `_request` boundary instead of hitting a real gateway -- this just applies the
 * identical substitution one layer further out (the browser's fetch boundary, via
 * Playwright's `page.route`) since there's no live gateway anywhere in this pipeline for the
 * real backend to proxy either. `POST /api/watchlist` is deliberately NOT stubbed here: it's
 * a real, always-available endpoint against this suite's own fixture-backed database, so the
 * add-to-watchlist half of the flow still exercises the genuine, unmocked backend like the
 * rest of this suite does.
 */
async function mockAvailableScanner(page: Page): Promise<void> {
  await page.route('**/api/ibkr/scanner/params', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        state: 'available',
        detail: null,
        categories: [{ code: 'TOP_PERC_GAIN', display_name: 'Top % Gainers' }],
      }),
    }),
  )
  await page.route('**/api/ibkr/scanner/run', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        state: 'available',
        detail: null,
        results: [
          {
            conid: 9990001,
            symbol: SCAN_RESULT_TICKER,
            company_name: 'Scanner E2E Fixture Co.',
            rank: 1,
          },
        ],
      }),
    }),
  )
}

/**
 * Scanner page (pages/ScannerPage.tsx): pick one of IBKR's own scan categories, run it,
 * review the resulting candidate list, and add a hit to the watchlist -- the same
 * golden-path shape dashboard/portfolio/watchlist.spec.ts already cover for the other
 * top-level nav destinations (frontend-market-scanner-page-followups, tracking the gap
 * PR #243's review found: "the persisted e2e suite currently has no coverage of the Scanner
 * page at all").
 */
test.describe('scanner: pick a category, run a scan, and add a hit to the watchlist', () => {
  test.afterAll(async ({ request }) => {
    // Safety-net cleanup, not the primary assertion -- same pattern watchlist.spec.ts's own
    // `afterAll` uses for GOOGL: guarantees SCAN_RESULT_TICKER is gone after this file
    // regardless of which test above ran or failed. A normal completed run has already
    // removed it via the UI in the test below, so this 404s far more often than it 204s --
    // both are expected outcomes, not a failure.
    const response = await request.delete(`/api/watchlist/${SCAN_RESULT_TICKER}`)
    expect([204, 404]).toContain(response.status())
  })

  test('running a scan and adding a hit to the watchlist', async ({ page }) => {
    await mockAvailableScanner(page)
    await page.goto('/scanner')

    await expect(page.getByRole('heading', { level: 1, name: 'Scanner' })).toBeVisible()

    const categoryPicker = page.getByRole('combobox', { name: 'Scan category' })
    await expect(categoryPicker).toBeVisible()
    await categoryPicker.click()
    await page.getByRole('option', { name: 'Top % Gainers' }).click()
    await page.getByRole('button', { name: 'Run scan' }).click()

    const resultsTable = page.getByRole('table', { name: 'Scanner results' })
    await expect(resultsTable).toBeVisible()
    await expect(scanResultRow(page)).toBeVisible()

    await scanResultRow(page).getByRole('button', { name: 'Add to watchlist' }).click()
    await expect(scanResultRow(page).getByRole('button', { name: 'Added' })).toBeVisible()

    // Confirms the add was a real write against the running backend, not just a client-side
    // optimistic flip -- mirrors watchlist.spec.ts's own preference for asserting against
    // real backend state where a flow mutates it.
    const watchlistResponse = await page.request.get('/api/watchlist')
    expect(watchlistResponse.ok()).toBe(true)
    const { items } = (await watchlistResponse.json()) as {
      items: Array<{ ticker: string }>
    }
    expect(items.map((item) => item.ticker)).toContain(SCAN_RESULT_TICKER)
  })
})

/**
 * The disabled/unavailable state (checklist item 1's other required scenario) needs no
 * route stubbing at all -- it's this e2e stack's real, always-on default (see
 * `mockAvailableScanner`'s own doc comment above), so this exercises the genuine, unmocked
 * backend response.
 */
test('scanner page shows the disabled/unavailable state, not an error, when IBKR is disabled', async ({
  page,
}) => {
  await page.goto('/scanner')

  await expect(page.getByRole('heading', { level: 1, name: 'Scanner' })).toBeVisible()
  await expect(page.getByText('Scanner unavailable')).toBeVisible()
  await expect(
    page.getByText('IBKR integration is disabled (FINTRADE_IBKR_ENABLED is not set).'),
  ).toBeVisible()
  await expect(page.getByRole('combobox')).toHaveCount(0)
  await expect(page.getByRole('table')).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveCount(0)
})
