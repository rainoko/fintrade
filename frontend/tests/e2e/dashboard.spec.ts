import { expect, test } from '@playwright/test'

/**
 * Dashboard page (pages/DashboardPage.tsx): equity stat cards, the risk summary card, the
 * sell-flagged positions card, and the positions-at-a-glance table, all sourced from GET
 * /api/portfolio + GET /api/portfolio/risk against the real backend (see
 * playwright.config.ts's fixture-mode webServer). Doesn't assert a specific position
 * count/total (the shared e2e database may already hold rows left by portfolio.spec.ts
 * depending on run order) — only that every section actually renders real data instead of
 * staying stuck on a loading/error state.
 */
test('dashboard renders equity summary, risk summary, sell-flagged positions, and positions at a glance', async ({
  page,
}) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible()

  // Equity stat cards (StatCard renders a plain label + value, no role of its own).
  await expect(page.getByText('Cash', { exact: true })).toBeVisible()
  await expect(page.getByText('Positions Value', { exact: true })).toBeVisible()
  await expect(page.getByText('Total Equity', { exact: true })).toBeVisible()

  // RiskSummaryCard (GET /api/portfolio/risk) -- waits past its own LoadingState.
  await expect(page.getByText('Total Open Risk', { exact: true })).toBeVisible()
  await expect(
    page.getByText('Positions Breaching 2% Rule', { exact: true }),
  ).toBeVisible()

  // SellFlaggedPositionsCard: either real flagged rows or its own empty-state message,
  // but one of the two must render either way (depends on the shared e2e database's
  // fixture positions/risk state at run time).
  const sellFlaggedTable = page.getByRole('table', { name: 'Positions flagged to sell' })
  const sellFlaggedEmptyState = page.getByText('No positions currently flagged to sell.')
  await expect(sellFlaggedTable.or(sellFlaggedEmptyState)).toBeVisible()

  // PositionsGlanceTable: either real rows or its own empty state, but the table region
  // itself (or the empty-state message replacing it) must render either way.
  const glanceTable = page.getByRole('table', { name: 'Positions at a glance' })
  const glanceEmptyState = page.getByText(
    'No positions yet. Add one from the Portfolio page to get started.',
  )
  await expect(glanceTable.or(glanceEmptyState)).toBeVisible()
})

test('dashboard shows no console errors on load', async ({ page }) => {
  const errors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') {
      errors.push(message.text())
    }
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible()
  await expect(page.getByText('Total Equity', { exact: true })).toBeVisible()

  expect(errors).toEqual([])
})
