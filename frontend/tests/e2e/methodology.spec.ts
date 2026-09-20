import { expect, test } from '@playwright/test'

/**
 * Methodology Reference page (pages/MethodologyPage.tsx, `/methodology`,
 * frontend-methodology-explainer) -- the one page in this app with no
 * server-side data behind it (features/methodology/data/methodologyContent.ts
 * is a static, local catalog), so this spec doesn't depend on any fixture
 * ticker's signal outcome the way stock-analysis.spec.ts does. Covers the
 * gap frontend-methodology-explainer-followups' checklist flagged: the
 * status filter, and the Stock Detail <-> Methodology cross-link round trip
 * (StockDetailPage's "Methodology reference" link one way,
 * MethodologyEntryCard's crossLinksTo link the other).
 */
test.describe('methodology reference page', () => {
  test('nav drawer link opens the page with its sections and status filter', async ({
    page,
  }) => {
    await page.goto('/')

    const nav = page.getByRole('navigation', { name: 'main navigation' })
    await nav.getByRole('link', { name: 'Methodology' }).click()

    await expect(page).toHaveURL(/\/methodology$/)
    await expect(
      page.getByRole('heading', { level: 1, name: 'Signals We Considered' }),
    ).toBeVisible()
    await expect(
      page.getByRole('heading', { name: 'Overview: the Triple Screen Trading System' }),
    ).toBeVisible()
    await expect(
      page.getByRole('heading', { name: /Screen 1 — The Tide/ }),
    ).toBeVisible()

    // Status filter (features/methodology/components/MethodologyStatusFilter.tsx):
    // deselecting every status hides every entries-bearing section and shows the
    // empty-selection notice, but the entries-free Overview section stays.
    const filterSection = page.getByRole('region', { name: 'Filter by implementation status' })
    await filterSection.getByRole('button', { name: 'Active — feeds the signal' }).click()
    await filterSection
      .getByRole('button', { name: 'Active — feeds portfolio risk & money management' })
      .click()
    await filterSection
      .getByRole('button', { name: 'Computed & exposed — informational only' })
      .click()
    await filterSection.getByRole('button', { name: 'Considered — not yet implemented' }).click()

    await expect(
      page.getByText(/No status is selected, so no indicator\/technique entries are shown/),
    ).toBeVisible()
    await expect(
      page.getByRole('heading', { name: 'Overview: the Triple Screen Trading System' }),
    ).toBeVisible()
    await expect(page.getByRole('heading', { name: /Screen 1 — The Tide/ })).not.toBeVisible()

    // Re-selecting one status brings its section back.
    await filterSection.getByRole('button', { name: 'Active — feeds the signal' }).click()
    await expect(page.getByRole('heading', { name: /Screen 1 — The Tide/ })).toBeVisible()
  })

  test('Stock Detail <-> Methodology cross-link round trip', async ({ page }) => {
    // Stock Detail -> Methodology, via the "Methodology reference" link
    // StockDetailPage.tsx renders under its page header.
    await page.goto('/stocks/AAPL')
    await page.getByRole('link', { name: 'Methodology reference' }).click()
    await expect(page).toHaveURL(/\/methodology$/)
    await expect(
      page.getByRole('heading', { level: 1, name: 'Signals We Considered' }),
    ).toBeVisible()

    // Methodology -> (Watchlist, then Stock Detail): a "Stock Detail page"
    // crossLinksTo entry resolves to the Watchlist page (this page has no
    // ticker context of its own -- MethodologyEntryCard.tsx's own
    // resolveCrossLinkPath doc comment), from which a real ticker link
    // continues on into Stock Detail.
    const tideCard = page.getByTestId('methodology-entry-card').filter({
      has: page.getByRole('heading', { name: 'Weekly Impulse System (Tide)' }),
    })
    await tideCard.getByRole('link', { name: /Stock Detail page/ }).click()
    await expect(page).toHaveURL(/\/watchlist$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Watchlist' })).toBeVisible()
  })
})
