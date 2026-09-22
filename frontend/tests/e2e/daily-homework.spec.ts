import { expect, test } from '@playwright/test'

/**
 * Daily Homework page (pages/DailyHomeworkPage.tsx, `/homework`,
 * frontend-daily-homework-page) -- Elder ch. 57's "Am I ready to trade?"
 * 5-question psychological readiness self-test. Filed as a follow-up from
 * PR #271's review (frontend-daily-homework-page-followups): the page
 * shipped with MSW-mocked component tests and a one-off manual browser
 * walkthrough, but no persisted e2e spec, so a future unrelated regression
 * on this route would go uncaught by `make e2e`.
 *
 * Runs against the real (fixture-mode) backend, like every other spec here.
 * `POST /api/daily-homework` upserts by calendar date (backend-daily-
 * homework-self-test), so re-running this spec against a database that
 * already has today's entry (an interrupted earlier run) still passes --
 * it just overwrites the same day's row, same as watchlist.spec.ts's own
 * tolerance for a pre-existing entry from an earlier interrupted run.
 * `yesterday_trading_score`'s suggestion endpoint depends on a "yesterday"
 * (relative to whatever real date the suite runs on) closed trade existing
 * in the fixture data, which it doesn't -- so that field is asserted at its
 * neutral (1) default rather than a specific suggested value, the same
 * "only assert what's deterministic against the real backend" reasoning
 * watchlist.spec.ts uses for its signal badge.
 */
test.describe('daily homework: nav, submit, and see the color-coded score banner', () => {
  test('nav drawer link opens the page, submitting the form shows the score banner, and it persists across reload', async ({
    page,
  }) => {
    await page.goto('/')

    const nav = page.getByRole('navigation', { name: 'main navigation' })
    await nav.getByRole('link', { name: 'Daily Homework' }).click()

    await expect(page).toHaveURL(/\/homework$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Daily Homework' })).toBeVisible()
    await expect(
      page.getByRole('heading', { name: 'Am I ready to trade today?' }),
    ).toBeVisible()

    // Every question defaults to the neutral (1) middle answer -- no fixture
    // trade closed "yesterday" relative to the real date this suite runs on,
    // so the suggestion endpoint has nothing to prefill.
    await expect(
      page.getByRole('combobox', { name: /How do I feel physically/ }),
    ).toHaveText(/^1 —/)
    await expect(
      page.getByRole('combobox', { name: /How did I trade yesterday/ }),
    ).toHaveText(/^1 —/)

    // Answer every question at its top (2) score except "yesterday", left at
    // its neutral default (1) -- total 9, the high-yellow "too perfect" band,
    // which exercises the same visually-distinct banner this PR's own
    // decisions entry added (a dedicated icon + "(too perfect)" label, not
    // just body copy).
    async function selectTop(label: string, option: string) {
      await page.getByRole('combobox', { name: new RegExp(label) }).click()
      await page.getByRole('option', { name: option }).click()
    }
    await selectTop('How do I feel physically', '2 — Good')
    await selectTop('Have I done my trade planning', '2 — Fully')
    await selectTop('What is my mood', '2 — Good')
    await selectTop('How busy is my schedule today', '2 — Clear')

    await page.getByRole('button', { name: 'Save' }).click()

    const banner = page.getByTestId('homework-score-banner')
    await expect(banner).toBeVisible()
    await expect(banner).toHaveText(/9\/10 -- YELLOW \(too perfect\)/)
    await expect(banner).toHaveText(/any change is bound to be for the worse/i)
    await expect(page.getByRole('button', { name: 'Update' })).toBeVisible()

    // Reloading re-fetches today's now-recorded entry and shows the same
    // band without resubmitting -- confirms the entry actually persisted
    // server-side, not just in local component state.
    await page.reload()
    await expect(page.getByTestId('homework-score-banner')).toBeVisible()
    await expect(page.getByTestId('homework-score-banner')).toHaveText(
      /9\/10 -- YELLOW \(too perfect\)/,
    )
    await expect(
      page.getByRole('combobox', { name: /How do I feel physically/ }),
    ).toHaveText(/^2 —/)
    await expect(page.getByRole('button', { name: 'Update' })).toBeVisible()
  })
})
