import { expect, test } from '@playwright/test'
import type { DailyHomeworkOut } from '../../src/api/homework'
import { formatDate } from '../../src/utils/format'

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
 *
 * The History table (`DailyHomeworkHistoryTable`, `GET /api/daily-homework`,
 * frontend-daily-homework-history) is covered below too -- PR #402's own
 * review flagged this spec as still only exercising the form+banner flow
 * despite adding that section (frontend-daily-homework-history-followups'
 * checklist). The expected row date is rendered via the real `formatDate`
 * helper (frontend/src/utils/format.ts, imported directly rather than
 * re-implemented inline -- a local copy of its `toLocaleDateString` options
 * wouldn't follow if those ever changed, per
 * frontend-daily-homework-history-followups-followups' checklist), applied
 * to the `date` the backend actually recorded in its POST response -- see
 * the `recordedDate` capture below for why that's read back from the
 * response rather than recomputed client-side.
 *
 * This is the first spec under tests/e2e/ to import anything from `src/`
 * directly (a type and a pure formatting helper) rather than through a
 * tests/-local module like tests/dateFixtures.ts -- see
 * docs/architecture/Testing.md's "Importing from src/ in an e2e spec"
 * convention (frontend-daily-homework-history-followups-followups-followups)
 * for what's allowed here (types, pure side-effect-free utilities) and what
 * isn't (components, hooks, anything with app-runtime/DOM dependencies).
 */
test.describe('daily homework: nav, submit, and see the color-coded score banner', () => {
  test('nav drawer link opens the page, submitting the form shows the score banner, and it persists across reload', async ({
    page,
  }) => {
    await page.goto('/')

    const nav = page.getByRole('navigation', { name: 'main navigation' })
    await nav.getByRole('link', { name: 'Daily Homework' }).click()

    await expect(page).toHaveURL(/\/homework$/)
    await expect(
      page.getByRole('heading', { level: 1, name: 'Daily Homework' }),
    ).toBeVisible()
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

    // Capture the POST's own response rather than recomputing "today"
    // client-side (e.g. `new Date().toISOString().slice(0, 10)`) after the
    // fact: the backend stamps the row's `date` via `today()`
    // (backend/app/time_utils.py) at POST-handling time, and several
    // assertions (the banner, the form re-render) elapse between that click
    // and the History-row assertion below -- recomputing "today" independently
    // at that later point could disagree with what the backend actually
    // stored if the run happens to straddle a UTC-midnight boundary in
    // between. Reading the date back from the response itself means the
    // assertion compares against the literal value the backend persisted,
    // so it can never disagree with it.
    const [postResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.url().endsWith('/api/daily-homework') &&
          response.request().method() === 'POST',
      ),
      page.getByRole('button', { name: 'Save' }).click(),
    ])
    const recordedDate = ((await postResponse.json()) as DailyHomeworkOut).date

    const banner = page.getByTestId('homework-score-banner')
    await expect(banner).toBeVisible()
    await expect(banner).toHaveText(/9\/10 -- YELLOW \(too perfect\)/)
    await expect(banner).toHaveText(/any change is bound to be for the worse/i)
    await expect(page.getByRole('button', { name: 'Update' })).toBeVisible()

    // The History table (below the form, same page -- frontend-daily-
    // homework-history) picks up the just-submitted entry via
    // useRecordDailyHomework's query invalidation, with no reload needed.
    // `e2e.db` is deleted fresh before every run (playwright.config.ts), so
    // this is the only row.
    await expect(page.getByRole('heading', { level: 2, name: 'History' })).toBeVisible()
    const historyTable = page.getByRole('table', { name: 'Daily homework history' })
    await expect(historyTable).toBeVisible()
    const todayHistoryRow = historyTable.getByRole('row').nth(1)
    await expect(todayHistoryRow.getByRole('cell').first()).toHaveText(
      formatDate(recordedDate),
    )
    await expect(todayHistoryRow.getByRole('cell').nth(6)).toHaveText('9')
    await expect(todayHistoryRow).toContainText('YELLOW (TOO PERFECT)')

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

    // The History row survives the reload too -- a fresh GET, not stale
    // client cache.
    await expect(
      page.getByRole('table', { name: 'Daily homework history' }).getByRole('row').nth(1),
    ).toContainText('YELLOW (TOO PERFECT)')
  })
})
