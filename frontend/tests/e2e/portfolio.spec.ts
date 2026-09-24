import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { isoDateWeeksAgo } from '../dateFixtures'

// A fixture ticker (see backend/app/data/fixture_provider.py) distinct from the one
// navigation/stock-analysis specs use (AAPL), so this spec's add/delete cycle can't be
// confused with state either of those leave behind.
const TICKER = 'MSFT'

// A fixture ticker distinct from every other one this suite uses (AAPL: navigation/
// stock-analysis; MSFT: the add/delete cycle above; GOOGL: watchlist.spec.ts) so the
// due-for-follow-up flow below can't be confused with any of their state either.
const FOLLOW_UP_TICKER = 'TSLA'

// Scoped to the positions table specifically (not just any row on the page): once a
// position is added, RiskPanel's separate "Portfolio risk" table also gets a row starting
// with the same ticker, which would otherwise make this locator ambiguous.
function positionRow(page: Page) {
  return page
    .getByRole('table', { name: 'Positions' })
    .getByRole('row', { name: new RegExp(`^${TICKER}\\b`) })
}

/**
 * Portfolio page (pages/PortfolioPage.tsx): view positions, add a position through the
 * dialog, see it reflected in both the positions table and the risk panel, then close it
 * through ClosePositionDialog (frontend-close-position-dialog). A single
 * `test.describe.serial` block (add depends on the page state the previous step left
 * behind) rather than one big test, so a failure midway reports exactly which step broke.
 *
 * Self-cleaning by design (the last step deletes what the first step added) and tolerant of
 * a pre-existing MSFT position from an earlier interrupted run (the add step accepts either
 * the "Added" or "Merged" success message -- see AddPositionDialog.tsx) -- both matter
 * because playwright.config.ts's webServer only guarantees a clean database at the start of
 * a whole `yarn test:e2e` invocation, not before each individual spec file.
 */
test.describe.serial('portfolio: view, add, and close a position', () => {
  test('portfolio page loads with a positions table', async ({ page }) => {
    await page.goto('/portfolio')
    await expect(page.getByRole('heading', { level: 1, name: 'Portfolio' })).toBeVisible()

    const positionsTable = page.getByRole('table', { name: 'Positions' })
    const emptyState = page.getByText('No positions yet. Add one to get started.')
    await expect(positionsTable.or(emptyState)).toBeVisible()
  })

  test('adding a position shows it in the positions table', async ({ page }) => {
    await page.goto('/portfolio')

    await page.getByRole('button', { name: 'Add Position' }).click()
    // Not filtered by accessible name: AddPositionDialog (unlike ConfirmDialog) doesn't wire
    // an explicit aria-labelledby, and only one MUI dialog is ever open at a time in this
    // app, so plain role scoping is unambiguous.
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('heading', { name: 'Add Position' })).toBeVisible()

    await dialog.getByLabel('Ticker').fill(TICKER)
    await dialog.getByLabel('Quantity').fill('10')
    await dialog.getByLabel('Avg Cost Basis').fill('300')
    await dialog.getByLabel('Entry Date').fill('2026-01-15')
    await dialog.getByRole('button', { name: 'Add Position' }).click()

    await expect(dialog.getByText(new RegExp(`(Added|Merged).*${TICKER}`))).toBeVisible()
    await dialog.getByRole('button', { name: 'Done' }).click()
    await expect(dialog).not.toBeVisible()

    await expect(positionRow(page)).toBeVisible()
  })

  test('the added position shows up in the risk panel', async ({ page }) => {
    await page.goto('/portfolio')

    await expect(page.getByText('Total Risk (Open + Realized)', { exact: true })).toBeVisible()

    const riskTable = page.getByRole('table', { name: 'Portfolio risk' })
    const riskEmptyState = page.getByText('No risk data available.')
    await expect(riskTable.or(riskEmptyState)).toBeVisible()
    // Not asserted further than "the panel rendered something": a position's price fetch
    // can legitimately fail and be silently excluded from the risk table by design (API.md,
    // RiskPanel.tsx's `missingTickers` note) -- this fixture ticker is expected to have a
    // price (backend/app/data/fixture_provider.py), but pinning this test to that internal
    // implementation detail would make it a change-detector for the fixture data shape
    // rather than a real assertion about the UI.
  })

  test('closing the position removes it from the table', async ({ page }) => {
    await page.goto('/portfolio')

    await positionRow(page)
      .getByRole('button', { name: `Delete ${TICKER}` })
      .click()

    // Not filtered by accessible name: ClosePositionDialog (like AddPositionDialog above)
    // doesn't wire an explicit aria-labelledby, and only one MUI dialog is ever open at a
    // time in this app, so plain role scoping is unambiguous.
    const closeDialog = page.getByRole('dialog')
    await expect(closeDialog).toBeVisible()
    await expect(closeDialog.getByRole('heading', { name: `Close Position: ${TICKER}` })).toBeVisible()
    await closeDialog.getByRole('button', { name: 'Close Position' }).click()
    await expect(closeDialog).not.toBeVisible()

    await expect(positionRow(page)).toHaveCount(0)
  })
})

// Scoped to the due-for-follow-up table specifically (not just any row on the page): once
// the seeded trade is reviewed it also shows up as a row in TradeJournalPanel's separate
// "Trade journal" table, which would otherwise make this locator ambiguous.
function dueForFollowUpRow(page: Page) {
  return page
    .getByRole('table', { name: 'Trades due for follow-up review' })
    .getByRole('row', { name: new RegExp(`^${FOLLOW_UP_TICKER}\\b`) })
}

/**
 * Reviews away any `FOLLOW_UP_TICKER` trade that's already due for follow-up review before
 * `seedDueForFollowUpTrade` seeds a fresh one -- defensive tweak mirroring the sibling 'view,
 * add, and close a position' block's own tolerance for a pre-existing MSFT position (see that
 * block's doc comment): `playwright.config.ts`'s webServer only guarantees a clean database at
 * the start of a whole `yarn test:e2e` invocation, not before each individual spec file, so an
 * earlier run interrupted between this block's `beforeAll` seed and its last test's review
 * would otherwise leave a stray unreviewed due TSLA trade behind. Left untouched by the
 * routine `make e2e`/`yarn test:e2e` path (which always wipes the database fresh, so this is
 * always a no-op there), but matters for `yarn test:e2e:ui` interactive debugging, whose
 * webServer persists across reruns. Without this, `seedDueForFollowUpTrade` would seed a
 * second unreviewed due TSLA trade and `dueForFollowUpRow(page)` would resolve to two rows,
 * turning every subsequent assertion/click on it into a Playwright strict-mode violation.
 */
async function clearPreexistingDueFollowUpTrades(request: APIRequestContext): Promise<void> {
  const dueResponse = await request.get('/api/portfolio/closed-trades', {
    params: { due_for_follow_up: true },
  })
  expect(dueResponse.ok()).toBe(true)
  const { items } = (await dueResponse.json()) as { items: Array<{ id: string; ticker: string }> }

  for (const trade of items.filter((item) => item.ticker === FOLLOW_UP_TICKER)) {
    const reviewResponse = await request.post(
      `/api/portfolio/closed-trades/${encodeURIComponent(trade.id)}/follow-up-review`,
      { data: { follow_up_notes: 'Cleared by e2e setup: leftover from an earlier interrupted run.' } },
    )
    expect(reviewResponse.ok()).toBe(true)
  }
}

/**
 * Seeds one closed trade for `FOLLOW_UP_TICKER` whose `exit_date` lands inside the backend's
 * 8-10-week due-for-follow-up window (API.md's `due_for_follow_up` query parameter, `app.api.
 * routers.portfolio`'s `_FOLLOW_UP_DUE_WINDOW_MIN`/`_MAX`) -- 9 weeks back, comfortably inside
 * both edges, matching the mocked-test suite's own choice for the same reason
 * (`frontend/tests/mocks/handlers.ts`'s `dueTradeFixture`). There's no UI path yet to backdate
 * a trade's exit date (`frontend-close-position-dialog`, still `planned`, is what will
 * eventually expose `DELETE .../positions/{id}`'s own `exit_price`/`exit_date` override in the
 * UI) -- so this drives the real running backend directly through the same two calls a
 * UI-driven add-then-manually-close flow would eventually make: `POST` a position dated well
 * before the intended exit, then `DELETE` it with an explicit `exit_price`/`exit_date` pair.
 */
async function seedDueForFollowUpTrade(request: APIRequestContext): Promise<void> {
  await clearPreexistingDueFollowUpTrades(request)

  const addResponse = await request.post('/api/portfolio/positions', {
    data: {
      ticker: FOLLOW_UP_TICKER,
      quantity: 10,
      avg_cost_basis: 200,
      entry_date: isoDateWeeksAgo(20),
    },
  })
  expect(addResponse.ok()).toBe(true)
  const position = (await addResponse.json()) as { id: string }

  const deleteResponse = await request.delete(
    `/api/portfolio/positions/${encodeURIComponent(position.id)}`,
    { params: { exit_price: 220, exit_date: isoDateWeeksAgo(9) } },
  )
  expect(deleteResponse.ok()).toBe(true)
}

/**
 * Trades due for their two-months-later follow-up review (`TradeFollowUpDuePanel.tsx`,
 * `FollowUpReviewDialog.tsx` -- Elder ch. 59 Trade Journal Section E): the due panel lists a
 * trade whose exit is 8-10 weeks back and not yet reviewed, recording a review through the
 * dialog removes it from that list. Seeded via direct API calls rather than the UI (see
 * `seedDueForFollowUpTrade`'s own doc) since there's no UI flow yet to backdate an exit date --
 * everything downstream of that seed (the due panel rendering it, opening the dialog, client-
 * side blank-notes validation, submitting, and the row disappearing and staying gone after a
 * reload) is driven through the real UI against the real running backend, same as every other
 * flow in this suite. A single `test.describe.serial` block, same reasoning as the add/delete
 * block above: submitting a review depends on the panel/dialog state the previous step left
 * behind.
 */
test.describe.serial('portfolio: due-for-follow-up review flow', () => {
  test.beforeAll(async ({ request }) => {
    await seedDueForFollowUpTrade(request)
  })

  test('a trade due for follow-up review appears in the due panel', async ({ page }) => {
    await page.goto('/portfolio')

    await expect(
      page.getByRole('heading', { level: 2, name: 'Due for Follow-Up Review' }),
    ).toBeVisible()
    await expect(dueForFollowUpRow(page)).toBeVisible()
  })

  test('submitting blank notes shows a validation error and keeps the dialog open', async ({
    page,
  }) => {
    await page.goto('/portfolio')

    await dueForFollowUpRow(page).getByRole('button', { name: 'Record Review' }).click()

    // Not filtered by accessible name, same reasoning as the "Add Position" dialog above:
    // only one MUI dialog is ever open at a time in this app.
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(
      dialog.getByRole('heading', { name: `Follow-Up Review: ${FOLLOW_UP_TICKER}` }),
    ).toBeVisible()

    await dialog.getByRole('button', { name: 'Save Review' }).click()

    await expect(dialog.getByText('Follow-up notes are required.')).toBeVisible()
    await expect(dialog).toBeVisible()

    await dialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(dialog).not.toBeVisible()
  })

  test('recording a review closes the dialog and removes the trade from the due list, even after a reload', async ({
    page,
  }) => {
    await page.goto('/portfolio')

    await dueForFollowUpRow(page).getByRole('button', { name: 'Record Review' }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await dialog
      .getByLabel('Follow-up notes')
      .fill('Shaken out on a normal pullback, then it ran without me -- give this setup more room next time.')
    await dialog.getByRole('button', { name: 'Save Review' }).click()

    await expect(dialog).not.toBeVisible()
    await expect(dueForFollowUpRow(page)).toHaveCount(0)

    await page.reload()
    await expect(dueForFollowUpRow(page)).toHaveCount(0)
  })
})
