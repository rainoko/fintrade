import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { resetPortfolioStore } from '../../tests/mocks/handlers'
import { server } from '../../tests/mocks/server'
import { renderWithProviders } from '../../tests/renderWithProviders'
import PortfolioPage from './PortfolioPage'

function renderPortfolioPage() {
  return renderWithProviders(
    <MemoryRouter>
      <PortfolioPage />
    </MemoryRouter>,
  )
}

describe('PortfolioPage', () => {
  beforeEach(() => {
    resetPortfolioStore()
  })

  afterEach(() => {
    resetPortfolioStore()
  })

  it('shows a loading state, then the equity stat cards and positions table', async () => {
    renderPortfolioPage()

    expect(screen.getByText('Loading portfolio...')).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Positions' })).toBeInTheDocument(),
    )

    expect(screen.getByText('Cash')).toBeInTheDocument()
    expect(screen.getByText('Positions Value')).toBeInTheDocument()
    expect(screen.getByText('Total Equity')).toBeInTheDocument()
    expect(screen.getByText('AAPL')).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Portfolio risk' })).toBeInTheDocument(),
    )
    expect(screen.getByText('Total Risk (Open + Realized)')).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Trade journal' })).toBeInTheDocument(),
    )
    expect(screen.getByRole('heading', { name: 'Trade Journal' })).toBeInTheDocument()
    expect(screen.getByText('ADSK')).toBeInTheDocument()
  })

  it('shows the empty state when the portfolio has no positions', async () => {
    server.use(
      http.get('/api/portfolio', () =>
        HttpResponse.json({
          trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
          equity: { cash: 5000, positions_value: 0, total: 5000 },
          positions: [],
        }),
      ),
      http.get('/api/portfolio/risk', () =>
        HttpResponse.json({
          trading_mode: { mode: 'swing', day_trader_timeframe_triple: null },
          total_open_risk_pct: 0,
          realized_losses_this_month_pct: 0,
          six_percent_rule_breached: false,
          positions: [],
        }),
      ),
    )

    renderPortfolioPage()

    await waitFor(() =>
      expect(
        screen.getByText('No positions yet. Add one to get started.'),
      ).toBeInTheDocument(),
    )
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('surfaces a network-level ApiError via common/ErrorState', async () => {
    server.use(http.get('/api/portfolio', () => HttpResponse.error()))

    renderPortfolioPage()

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Connection error')).toBeInTheDocument()
  })

  // Regression test for the PR #258 review finding: PositionsTable and
  // RiskPanel both independently call usePortfolioRisk(), and both render on
  // this page -- a GET /api/portfolio/risk failure must surface exactly one
  // role="alert" ErrorState (RiskPanel's), not two identical stacked ones.
  it("surfaces exactly one ErrorState (RiskPanel's) when GET /api/portfolio/risk fails, not a duplicate from PositionsTable", async () => {
    server.use(
      http.get('/api/portfolio/risk', () =>
        HttpResponse.json(
          { detail: 'Market data provider unavailable' },
          { status: 503 },
        ),
      ),
    )

    renderPortfolioPage()

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Positions' })).toBeInTheDocument(),
    )
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())

    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.getByText('Service unavailable')).toBeInTheDocument()
    expect(screen.getByText('Market data provider unavailable')).toBeInTheDocument()
    // The positions table itself still renders, with its risk columns
    // falling back to '—' rather than duplicating RiskPanel's own alert.
    expect(screen.getByRole('table', { name: 'Positions' })).toBeInTheDocument()
  })

  // This test's own timeout is raised above vitest's 5000ms default (see
  // backend-indicator-seasons-followups task decisions): it renders the
  // whole PortfolioPage (positions table + risk panel + trade journal, all
  // hydrated from their own mocked GETs) and then drives four real
  // userEvent.type() field entries plus two clicks through a mounted MUI
  // Dialog -- legitimately more real DOM/event work than any other test in
  // this file. That's fast enough in isolation and on a coverage-less full
  // run, but v8 coverage instrumentation's per-file overhead during a full
  // suite run intermittently pushes it past 5000ms; it comfortably clears
  // 15000ms every time under the same load. Bumping just this test's
  // timeout (rather than the project-wide default, which would mask a
  // future genuinely-hung test elsewhere) is the fix, not a change to the
  // component or the interaction sequence itself, which do no unnecessary
  // real waiting (no timers/debounce; retries are already disabled in
  // tests/renderWithProviders.tsx).
  it('adds a new position end to end and reflects it in the refreshed table', async () => {
    const user = userEvent.setup()
    renderPortfolioPage()

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Positions' })).toBeInTheDocument(),
    )

    await user.click(screen.getByRole('button', { name: 'Add Position' }))
    await user.type(screen.getByLabelText('Ticker'), 'MSFT')
    await user.type(screen.getByLabelText('Quantity'), '5')
    await user.type(screen.getByLabelText('Avg Cost Basis'), '400')
    await user.type(screen.getByLabelText('Entry Date'), '2026-02-01')
    await user.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Add Position' }),
    )

    await waitFor(() =>
      expect(screen.getByText('Added MSFT to your portfolio.')).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: 'Done' }))

    await waitFor(() => {
      const table = screen.getByRole('table', { name: 'Positions' })
      expect(within(table).getByText('MSFT')).toBeInTheDocument()
    })
  }, 15000)

  it('deletes a position end to end and removes it from the refreshed table', async () => {
    const user = userEvent.setup()
    renderPortfolioPage()

    await waitFor(() => expect(screen.getByText('AAPL')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Delete AAPL' }))
    await user.click(screen.getByRole('button', { name: 'Close Position' }))

    await waitFor(() =>
      expect(
        screen.getByText('No positions yet. Add one to get started.'),
      ).toBeInTheDocument(),
    )
  })

  // frontend-ibkr-portfolio-preload: the "Preload from IBKR" action is gated
  // on GET /api/ibkr/status, which defaults to 'disabled' (the real backend's
  // own default, tests/mocks/handlers.ts) -- so every other test above never
  // sees this button enabled, matching the real app's out-of-the-box state.
  describe('Preload from IBKR', () => {
    it('renders the button disabled, with an explanatory tooltip, when IBKR is disabled (the default)', async () => {
      renderPortfolioPage()

      await waitFor(() =>
        expect(screen.getByRole('button', { name: 'Preload from IBKR' })).toBeInTheDocument(),
      )
      expect(screen.getByRole('button', { name: 'Preload from IBKR' })).toBeDisabled()
    })

    it('enables the button once GET /api/ibkr/status reports available, and opens the review dialog on click', async () => {
      server.use(
        http.get('/api/ibkr/status', () => HttpResponse.json({ state: 'available', detail: null })),
      )
      const user = userEvent.setup()
      renderPortfolioPage()

      await waitFor(() =>
        expect(screen.getByRole('table', { name: 'Positions' })).toBeInTheDocument(),
      )
      await waitFor(() =>
        expect(screen.getByRole('button', { name: 'Preload from IBKR' })).toBeEnabled(),
      )
      await user.click(screen.getByRole('button', { name: 'Preload from IBKR' }))

      expect(screen.getByRole('dialog')).toBeInTheDocument()
      await waitFor(() =>
        expect(screen.getByText('Conflicting tickers (1)')).toBeInTheDocument(),
      )
      // The dialog resolves AAPL's conflict against PortfolioPage's own
      // already-loaded usePortfolio() positions, not a second fetch.
      const conflictTable = screen.getByRole('table', { name: 'Conflicting IBKR positions' })
      expect(within(conflictTable).getByText('AAPL')).toBeInTheDocument()
      expect(within(conflictTable).queryByText('Not found locally')).not.toBeInTheDocument()
    })

    it('preloads NVDA end to end and shows it in the refreshed positions table', async () => {
      server.use(
        http.get('/api/ibkr/status', () => HttpResponse.json({ state: 'available', detail: null })),
      )
      const user = userEvent.setup()
      renderPortfolioPage()

      await waitFor(() =>
        expect(screen.getByRole('table', { name: 'Positions' })).toBeInTheDocument(),
      )
      await waitFor(() =>
        expect(screen.getByRole('button', { name: 'Preload from IBKR' })).toBeEnabled(),
      )
      await user.click(screen.getByRole('button', { name: 'Preload from IBKR' }))
      await waitFor(() =>
        expect(screen.getByRole('button', { name: 'Import 1 position' })).toBeInTheDocument(),
      )
      await user.click(screen.getByRole('button', { name: 'Import 1 position' }))
      await waitFor(() =>
        expect(screen.getByText('Imported 1 position from IBKR.')).toBeInTheDocument(),
      )
      await user.click(screen.getByRole('button', { name: 'Done' }))

      await waitFor(() => {
        const table = screen.getByRole('table', { name: 'Positions' })
        expect(within(table).getByText('NVDA')).toBeInTheDocument()
        // The still-conflicting AAPL position was never touched/merged.
        expect(within(table).getByText('AAPL')).toBeInTheDocument()
      })
    }, 15000)
  })
})
