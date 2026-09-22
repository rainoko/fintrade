import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { PositionOut, RiskResponse } from '../../../api/portfolio'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import PositionsTable, { type PositionsTableProps } from './PositionsTable'

function renderPositionsTable(positions: PositionsTableProps['positions']) {
  return renderWithProviders(
    <MemoryRouter>
      <PositionsTable positions={positions} />
    </MemoryRouter>,
  )
}

function mockRisk(response: RiskResponse) {
  server.use(http.get('/api/portfolio/risk', () => HttpResponse.json(response)))
}

const positions: PositionOut[] = [
  {
    id: 'pos_123',
    ticker: 'AAPL',
    quantity: 100,
    avg_cost_basis: 195.3,
    entry_date: '2026-05-14',
    current_price: 228.9,
    unrealized_pnl_pct: 17.2,
    signal: 'BUY',
    confidence: 72,
    confidence_band: 'High',
  },
  {
    id: 'pos_456',
    ticker: 'ZZZZ',
    quantity: 10,
    avg_cost_basis: 50,
    entry_date: '2026-06-01',
    current_price: null,
    unrealized_pnl_pct: null,
    signal: null,
    confidence: null,
    confidence_band: null,
  },
]

describe('PositionsTable', () => {
  it('renders a row per position with formatted currency/percentage cells and a signal badge', async () => {
    mockRisk({
      total_open_risk_pct: 1.8,
      realized_losses_this_month_pct: 0,
      six_percent_rule_breached: false,
      positions: [
        {
          id: 'pos_123',
          ticker: 'AAPL',
          protective_stop: 210.15,
          position_risk_pct: 1.8,
          two_percent_rule_breached: false,
          exit_flags: [],
          profit_target: {
            price: 245.0,
            source: 'channel',
            distance_to_stop: 9.3,
            distance_to_target: 18.6,
            reward_risk_ratio: 2.0,
            meets_minimum_reward_risk: true,
          },
        },
      ],
    })
    renderPositionsTable(positions)

    const table = screen.getByRole('table')
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)

    expect(within(rows[0]).getByRole('link', { name: 'AAPL' })).toHaveAttribute(
      'href',
      '/stocks/AAPL',
    )
    expect(within(rows[0]).getByText('$195.30')).toBeInTheDocument()
    expect(within(rows[0]).getByText('$228.90')).toBeInTheDocument()
    expect(within(rows[0]).getByText('+17.20%')).toBeInTheDocument()
    const aaplBadge = within(rows[0]).getByTestId('signal-badge')
    expect(aaplBadge).toHaveTextContent('BUY')

    // Protective Stop/Profit Target columns (frontend-position-risk-columns)
    // read from GET /api/portfolio/risk, cross-referenced by ticker.
    await waitFor(() =>
      expect(within(rows[0]).getByText('$210.15')).toBeInTheDocument(),
    )
    expect(within(rows[0]).getByText('$245.00')).toBeInTheDocument()
    expect(within(rows[0]).getByText('2.0:1')).toBeInTheDocument()
  })

  it('renders an em dash for null current_price/unrealized_pnl_pct/signal, and for a ticker missing from the risk response', async () => {
    mockRisk({
      total_open_risk_pct: 0,
      realized_losses_this_month_pct: 0,
      six_percent_rule_breached: false,
      positions: [],
    })
    renderPositionsTable(positions)

    const table = screen.getByRole('table')
    const rows = within(table).getAllByRole('row').slice(1)
    const zzzzRow = rows[1]

    expect(within(zzzzRow).getByText('ZZZZ')).toBeInTheDocument()
    const cells = within(zzzzRow).getAllByRole('cell')
    expect(cells.map((cell) => cell.textContent)).toContain('—')
    expect(within(zzzzRow).queryByTestId('signal-badge')).not.toBeInTheDocument()

    // ZZZZ is absent from the (mocked, empty) risk response above -- both
    // new columns fall back to '—' rather than crashing on a missing entry,
    // matching RiskPanel's own graceful-degrade convention for the same case.
    await waitFor(() => expect(within(zzzzRow).getAllByText('—').length).toBeGreaterThan(0))
  })

  it('sorts by current_price, with the null value sorting last', async () => {
    const user = userEvent.setup()
    renderPositionsTable(positions)

    await user.click(screen.getByRole('button', { name: 'Current Price' }))

    const table = screen.getByRole('table')
    const rows = within(table).getAllByRole('row').slice(1)
    expect(within(rows[0]).getByText('AAPL')).toBeInTheDocument()
    expect(within(rows[1]).getByText('ZZZZ')).toBeInTheDocument()
  })

  it('renders the empty state when there are no positions', () => {
    renderPositionsTable([])

    expect(
      screen.getByText('No positions yet. Add one to get started.'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('opens the close-position dialog before closing, and cancels without closing', async () => {
    const user = userEvent.setup()
    renderPositionsTable(positions)

    await user.click(screen.getByRole('button', { name: 'Delete AAPL' }))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/close aapl \(100 shares\)/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('closes the position on confirm with the default (unspecified) exit reason and no override', async () => {
    let requestedUrl: URL | undefined
    server.use(
      http.delete('/api/portfolio/positions/:id', ({ request }) => {
        requestedUrl = new URL(request.url)
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderPositionsTable(positions)

    await user.click(screen.getByRole('button', { name: 'Delete AAPL' }))
    await user.click(screen.getByRole('button', { name: 'Close Position' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(requestedUrl?.searchParams.get('exit_reason')).toBe('unspecified')
    expect(requestedUrl?.searchParams.get('exit_price')).toBeNull()
    expect(requestedUrl?.searchParams.get('exit_date')).toBeNull()
  })

  it('closes the position with a chosen exit reason and a manual exit price/date override', async () => {
    let requestedUrl: URL | undefined
    server.use(
      http.delete('/api/portfolio/positions/:id', ({ request }) => {
        requestedUrl = new URL(request.url)
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderPositionsTable(positions)

    await user.click(screen.getByRole('button', { name: 'Delete AAPL' }))
    await user.click(screen.getByRole('combobox', { name: 'Exit reason' }))
    await user.click(screen.getByRole('option', { name: 'Target hit' }))
    await user.click(
      screen.getByRole('checkbox', {
        name: "Backfill a historical exit price/date instead of today's live price",
      }),
    )
    await user.type(screen.getByLabelText('Exit Price'), '230')
    await user.type(screen.getByLabelText('Exit Date'), '2026-06-15')
    await user.click(screen.getByRole('button', { name: 'Close Position' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(requestedUrl?.searchParams.get('exit_reason')).toBe('target_hit')
    expect(requestedUrl?.searchParams.get('exit_price')).toBe('230')
    expect(requestedUrl?.searchParams.get('exit_date')).toBe('2026-06-15')
  })

  it('disables the row Delete button while its deletion is pending, preventing a double-click race', async () => {
    // Delays the DELETE response so the pending window is observable -- without this the
    // mutation settles before the second click assertion below could ever run.
    let resolveDelete: () => void = () => {}
    server.use(
      http.delete('/api/portfolio/positions/:id', async () => {
        await new Promise<void>((resolve) => {
          resolveDelete = resolve
        })
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderPositionsTable(positions)

    await user.click(screen.getByRole('button', { name: 'Delete AAPL' }))
    await user.click(screen.getByRole('button', { name: 'Close Position' }))

    // Unlike the old bare ConfirmDialog (which closed synchronously on confirm, regardless of
    // outcome), ClosePositionDialog only closes on a *successful* close -- so while the DELETE
    // above is deliberately held pending, the dialog is still open and MUI's own modal behavior
    // (aria-hidden + a blocking backdrop over the rest of the page) already makes the
    // underlying row's Delete button unreachable through the UI. The one way the dialog itself
    // can still be dismissed early while a delete is genuinely in flight is a backdrop click
    // (its own Cancel button is disabled while pending, but a backdrop click isn't gated on
    // that, matching every other dialog in this app) -- so that's what actually exercises this
    // guard now. (Escape would conceptually do the same, but MUI's own Button moves focus off
    // itself the instant it becomes disabled by `loading`, which stops the keydown from ever
    // reaching the Modal's own listener in this environment -- a backdrop click has no such
    // focus dependency.)
    const backdrop = document.querySelector('.MuiBackdrop-root') as HTMLElement
    await user.click(backdrop)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Delete AAPL' })).toBeDisabled(),
    )
    // A row unrelated to the in-flight deletion stays interactive.
    expect(screen.getByRole('button', { name: 'Delete ZZZZ' })).not.toBeDisabled()

    resolveDelete()
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Delete AAPL' })).not.toBeDisabled(),
    )
  })

  it('degrades silently to \'—\' (no own ErrorState) when GET /api/portfolio/risk fails, since RiskPanel already surfaces this failure on the same PortfolioPage', async () => {
    let riskRequestSettled = false
    server.use(
      http.get('/api/portfolio/risk', () => {
        riskRequestSettled = true
        return HttpResponse.json({ detail: 'Market data provider unavailable' }, { status: 503 })
      }),
    )
    renderPositionsTable(positions)

    // Wait for the (failing) risk request to actually settle before asserting
    // on its absence of effect, so this test can't pass merely because the
    // request hadn't resolved yet.
    await waitFor(() => expect(riskRequestSettled).toBe(true))

    // The table renders normally, with the risk columns falling back to '—'
    // -- indistinguishable from a ticker missing from a *successful* risk
    // response, by design: PositionsTable and RiskPanel both independently
    // call usePortfolioRisk() and both render on PortfolioPage, so only
    // RiskPanel owns the page-level ErrorState for this shared failure (see
    // this component's own doc comment and this task's `decisions` entry).
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    const row = screen.getByRole('row', { name: /AAPL/ })
    expect(within(row).getAllByText('—').length).toBeGreaterThan(0)
  })

  it('surfaces a 404 ApiError via common/ErrorState inside the still-open dialog when the position no longer exists', async () => {
    server.use(
      http.delete('/api/portfolio/positions/:id', () =>
        HttpResponse.json({ detail: 'Position not found' }, { status: 404 }),
      ),
    )
    const user = userEvent.setup()
    renderPositionsTable(positions)

    await user.click(screen.getByRole('button', { name: 'Delete AAPL' }))
    await user.click(screen.getByRole('button', { name: 'Close Position' }))

    // The dialog only closes on a successful close -- an error leaves it open with its own
    // ErrorState visible, rather than the alert appearing after the dialog has already vanished
    // (the earlier bare ConfirmDialog's behavior).
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('Not found')).toBeInTheDocument()
    expect(screen.getByText('Position not found')).toBeInTheDocument()
  })

  it('clears a previous close-position error when Cancel is clicked, so reopening for another row starts clean', async () => {
    server.use(
      http.delete('/api/portfolio/positions/:id', () =>
        HttpResponse.json({ detail: 'Position not found' }, { status: 404 }),
      ),
    )
    const user = userEvent.setup()
    renderPositionsTable(positions)

    await user.click(screen.getByRole('button', { name: 'Delete AAPL' }))
    await user.click(screen.getByRole('button', { name: 'Close Position' }))
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Delete ZZZZ' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
