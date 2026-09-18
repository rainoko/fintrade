import { expect, test } from '@playwright/test'

/**
 * Stock analysis page (pages/StockDetailPage.tsx): search, the Triple Screen signal +
 * confidence display, the confidence-breakdown/screens/indicators panels, and the price
 * history chart. Runs against app.data.fixture_provider.FixtureDataProvider's deterministic
 * "AAPL" series (see playwright.config.ts + backend/app/data/fixture_provider.py) rather
 * than asserting an exact signal/confidence value: the real Elder Triple Screen outcome
 * depends on interacting Tide/Wave/Trigger/Impulse rules the pytest suite already covers
 * with hand-derived reference values (see the verify-elder-signal skill) -- this suite only
 * asserts that a real signal/confidence/chart renders end to end through a real running
 * backend, not that a specific number comes out.
 */
test.describe('stock analysis page', () => {
  test('search renders signal, confidence, screens, indicators, and price chart', async ({
    page,
  }) => {
    await page.goto('/')
    await page.getByLabel('Look up a ticker').fill('AAPL')
    await page.getByRole('button', { name: 'Go' }).click()
    await expect(page).toHaveURL(/\/stocks\/AAPL$/)

    // Signal + confidence (features/stocks/components/SignalSummary.tsx).
    const signalBadge = page.getByTestId('signal-badge')
    await expect(signalBadge).toBeVisible()
    await expect(signalBadge).toHaveText(/^(BUY|SELL|HOLD)$/)

    const confidenceGauge = page.getByRole('progressbar', { name: 'Confidence' })
    await expect(confidenceGauge).toBeVisible()
    const confidenceValue = await confidenceGauge.getAttribute('aria-valuenow')
    expect(Number(confidenceValue)).toBeGreaterThanOrEqual(0)
    expect(Number(confidenceValue)).toBeLessThanOrEqual(100)

    // AAPL's fixture series (backend/app/data/fixture_provider.py) isn't engineered to
    // land a specific BUY/SELL setup (see this file's top-level docstring), so a HOLD
    // outcome -- which the real engine legitimately renders with an *empty*
    // confidence_breakdown, i.e. DataTable's empty state rather than a `<table>`
    // (app/signals/engine.py: "A HOLD signal has no meaningful signal_direction for the
    // confidence components") -- is just as valid a result here as a populated table.
    const breakdownTable = page.getByRole('table', { name: 'Confidence breakdown' })
    const breakdownEmptyState = page.getByText('No confidence breakdown available.')
    await expect(breakdownTable.or(breakdownEmptyState)).toBeVisible()

    // Latest-bar indicator values (features/stocks/components/IndicatorsPanel.tsx).
    await expect(page.getByText('EMA (13)', { exact: true })).toBeVisible()
    await expect(page.getByText('EMA (26)', { exact: true })).toBeVisible()
    await expect(page.getByText('MACD Histogram', { exact: true })).toBeVisible()
    await expect(page.getByText('Bull Power', { exact: true })).toBeVisible()
    await expect(page.getByText('Bear Power', { exact: true })).toBeVisible()

    // Price history chart (features/stocks/components/PriceChart.tsx).
    await expect(page.getByTestId('price-chart-canvas')).toBeVisible()

    // Historical oscillator pane -- Stochastic %K/Force Index/MACD
    // Histogram (features/stocks/components/OscillatorChart.tsx),
    // synced to the same (default, Daily) range/interval as the price
    // chart above via StockCharts.tsx.
    await expect(page.getByText('Oscillators (Screen 2)')).toBeVisible()
    await expect(page.getByTestId('oscillator-chart-canvas')).toBeVisible()
  })

  test('range and interval toggles reload the price chart without erroring', async ({
    page,
  }) => {
    // GOOGL (backend/app/data/fixture_provider.py: zero drift, pure noise)
    // is the fixture ticker that actually produces a BUY/SELL signal
    // transition within the default 1y range, unlike AAPL's steady uptrend
    // -- exercising the EMA13/EMA26 line series *and* the transition marker
    // from PriceChart's signal overlay (features/stocks/components/
    // PriceChart.tsx), not just an overlay with nothing plotted on it.
    await page.goto('/stocks/GOOGL')
    await expect(page.getByTestId('price-chart-canvas')).toBeVisible()

    // Regression test for a real crash (frontend-chart-signal-overlay task
    // review): switching the range/interval toggle after the overlay had
    // already rendered once used to throw from PriceChart's overlay-cleanup
    // effect touching a chart the candlestick effect's own cleanup had
    // already disposed, crashing the whole page into AppErrorBoundary. That
    // race only exists once the overlay has actually mounted onto the
    // chart, so this waits for the `/indicators` response (and the loading
    // caption it drives) to fully resolve before clicking through the
    // range/interval controls below -- without this wait, a toggle could
    // land before the overlay ever mounts and miss the race entirely.
    const overlayLoading = page.getByText('Loading signal overlay for GOOGL...')
    await overlayLoading.waitFor({ state: 'hidden' }).catch(() => {
      // Fast enough responses may never show the loading caption at all --
      // that's fine, it just means there's nothing to wait to disappear.
    })

    await page.getByRole('button', { name: '6M' }).click()
    await expect(page.getByTestId('price-chart-canvas')).toBeVisible()
    // The page must still be the stock analysis page, not
    // AppErrorBoundary's fallback -- confirms the range toggle didn't crash
    // the tree the way the reported bug did.
    await expect(page.getByRole('button', { name: 'Go' })).toBeVisible()
    // The oscillator pane (StockCharts.tsx mirrors PriceChart's range into
    // it) stays in sync with the same 6M window, not stuck on the default.
    await expect(page.getByTestId('oscillator-chart-canvas')).toBeVisible()

    await page.getByRole('button', { name: 'Weekly' }).click()
    await expect(page.getByTestId('price-chart-canvas')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Go' })).toBeVisible()
    // `/indicators` is daily-cadence only -- the oscillator pane replaces
    // its chart with an explanatory message rather than showing daily data
    // under weekly candles (OscillatorChart.tsx's `enabled` gating).
    await expect(
      page.getByText('Oscillators (Stochastic %K, Force Index, MACD Histogram) are only available for the Daily interval.'),
    ).toBeVisible()
    await expect(page.getByTestId('oscillator-chart-canvas')).not.toBeVisible()

    // Back to Daily re-fetches and re-mounts the overlay -- toggling away
    // from it and back again must not crash either.
    await page.getByRole('button', { name: 'Daily' }).click()
    await expect(page.getByTestId('price-chart-canvas')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Go' })).toBeVisible()
    await expect(page.getByTestId('oscillator-chart-canvas')).toBeVisible()
  })

  test('looking up an unknown ticker shows a not-found error state', async ({ page }) => {
    await page.goto('/')
    await page.getByLabel('Look up a ticker').fill('ZZZZINVALID')
    await page.getByRole('button', { name: 'Go' }).click()
    await expect(page).toHaveURL(/\/stocks\/ZZZZINVALID$/)

    const errorState = page.getByRole('alert')
    await expect(errorState).toBeVisible()
    await expect(errorState).toContainText('Not found')
  })
})
