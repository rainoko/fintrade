import { expect, test } from '@playwright/test'

/**
 * App-shell navigation (components/layout/AppShell.tsx + NavDrawer.tsx): the persistent
 * nav's Dashboard/Portfolio links, and the ticker search box's route into Stock Detail
 * (App.tsx's route table). Runs against the real backend (see playwright.config.ts) but
 * doesn't depend on any specific portfolio/ticker data — purely a routing/shell smoke test.
 */
test.describe('app-shell navigation', () => {
  test('nav drawer links switch between Dashboard and Portfolio', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible()

    const nav = page.getByRole('navigation', { name: 'main navigation' })
    await expect(nav.getByRole('link', { name: 'Dashboard' })).toBeVisible()

    await nav.getByRole('link', { name: 'Portfolio' }).click()
    await expect(page).toHaveURL(/\/portfolio$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Portfolio' })).toBeVisible()

    await nav.getByRole('link', { name: 'Dashboard' }).click()
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible()
  })

  test('ticker search box navigates from Dashboard into Stock Detail', async ({
    page,
  }) => {
    await page.goto('/')

    await page.getByLabel('Look up a ticker').fill('AAPL')
    await page.getByRole('button', { name: 'Go' }).click()

    await expect(page).toHaveURL(/\/stocks\/AAPL$/)
    await expect(page.getByRole('heading', { level: 1, name: 'AAPL' })).toBeVisible()
  })

  test('unknown route falls back to the not-found page', async ({ page }) => {
    await page.goto('/this-route-does-not-exist')
    await expect(page.getByText(/not found/i)).toBeVisible()
  })
})
