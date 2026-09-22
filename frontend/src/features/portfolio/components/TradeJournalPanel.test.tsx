import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { ClosedTradesResponse } from '../../../api/portfolio'
import { theme } from '../../../theme/theme'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import TradeJournalPanel from './TradeJournalPanel'

function mockClosedTrades(response: ClosedTradesResponse) {
  server.use(http.get('/api/portfolio/closed-trades', () => HttpResponse.json(response)))
}

function renderTradeJournalPanel() {
  return renderWithProviders(
    <MemoryRouter>
      <TradeJournalPanel />
    </MemoryRouter>,
  )
}

describe('TradeJournalPanel', () => {
  it('renders the ADSK book example row: entry/exit price+date, realized P/L, exit reason, and all three grades', async () => {
    mockClosedTrades({
      items: [
        {
          id: 'trade_abc123',
          ticker: 'ADSK',
          quantity: 100,
          entry_price: 51.77,
          entry_date: '2026-03-02',
          exit_price: 53.78,
          exit_date: '2026-03-09',
          realized_pnl: 201.0,
          exit_reason: 'target_hit',
          buy_grade_pct: 97.3,
          sell_grade_pct: 35.5,
          trade_grade_pct: 32.1,
        },
      ],
    })

    renderTradeJournalPanel()

    expect(screen.getByText('Loading trade journal...')).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Trade journal' })).toBeInTheDocument(),
    )

    const row = screen.getByText('ADSK').closest('tr') as HTMLElement
    expect(within(row).getByRole('link', { name: 'ADSK' })).toHaveAttribute(
      'href',
      '/stocks/ADSK',
    )
    expect(within(row).getByText('100')).toBeInTheDocument()
    expect(within(row).getByText('Mar 2, 2026 @ $51.77')).toBeInTheDocument()
    expect(within(row).getByText('Mar 9, 2026 @ $53.78')).toBeInTheDocument()

    const pnl = within(row).getByText('+$201.00')
    expect(pnl).toHaveStyle({ color: theme.palette.success.main })

    expect(within(row).getByText('Target hit')).toBeInTheDocument()

    // Buy grade 97.3% -- above the 50% "very good" threshold, so bold.
    const buyGrade = within(row).getByText('97.3%')
    expect(buyGrade).toHaveStyle({ fontWeight: '700' })
    // Sell grade 35.5% -- below the threshold, not bold.
    const sellGrade = within(row).getByText('35.5%')
    expect(sellGrade).toHaveStyle({ fontWeight: '400' })
    // Trade grade 32.1% -- above its own 30% "A trade" threshold, so bold.
    const tradeGrade = within(row).getByText('32.1%')
    expect(tradeGrade).toHaveStyle({ fontWeight: '700' })
  })

  it('does not bold a grade at exactly its "good" threshold, since the threshold copy says "over" it', async () => {
    mockClosedTrades({
      items: [
        {
          id: 'trade_boundary',
          ticker: 'MSFT',
          quantity: 1,
          entry_price: 100,
          entry_date: '2026-01-01',
          exit_price: 110,
          exit_date: '2026-01-05',
          realized_pnl: 10,
          exit_reason: 'target_hit',
          // Exactly at the buy/sell "over 50%" anchor -- must render as the
          // non-bold weight, matching the strictly-"over" MetricHelp/backend
          // copy (frontend-trade-journal-followups).
          buy_grade_pct: 50,
          sell_grade_pct: 50,
          trade_grade_pct: 30,
        },
      ],
    })

    renderTradeJournalPanel()
    await waitFor(() => expect(screen.getByText('MSFT')).toBeInTheDocument())

    const row = screen.getByText('MSFT').closest('tr') as HTMLElement
    const grades = within(row).getAllByText('50.0%')
    expect(grades).toHaveLength(2)
    grades.forEach((grade) => expect(grade).toHaveStyle({ fontWeight: '400' }))
    // Trade Grade keeps its inclusive >= 30% "A trade" cutoff.
    expect(within(row).getByText('30.0%')).toHaveStyle({ fontWeight: '700' })
  })

  it('sorts by a nullable grade column, missing values last', async () => {
    // A genuine null in the column actually being sorted (Buy Grade) --
    // unlike this test's own prior version, which only varied
    // sell_grade_pct/trade_grade_pct (columns not sorted here) and so never
    // exercised the "missing values last" claim its own name/comment makes
    // for this call site. Mirrors PositionsTable.test.tsx's equivalent
    // current_price sort test, which does use a real null in the sorted
    // column (docs/tasks/frontend-trade-journal-followups-followups.json).
    const user = userEvent.setup()
    mockClosedTrades({
      items: [
        {
          id: 'trade_a',
          ticker: 'AAA',
          quantity: 1,
          entry_price: 10,
          entry_date: '2026-01-01',
          exit_price: 11,
          exit_date: '2026-01-05',
          realized_pnl: 1,
          exit_reason: 'target_hit',
          buy_grade_pct: 40,
          sell_grade_pct: null,
          trade_grade_pct: null,
        },
        {
          id: 'trade_b',
          ticker: 'BBB',
          quantity: 1,
          entry_price: 10,
          entry_date: '2026-01-01',
          exit_price: 11,
          exit_date: '2026-01-05',
          realized_pnl: 1,
          exit_reason: 'target_hit',
          buy_grade_pct: 90,
          sell_grade_pct: null,
          trade_grade_pct: null,
        },
        {
          id: 'trade_c',
          ticker: 'CCC',
          quantity: 1,
          entry_price: 10,
          entry_date: '2026-01-01',
          exit_price: 11,
          exit_date: '2026-01-05',
          realized_pnl: 1,
          exit_reason: 'target_hit',
          buy_grade_pct: null,
          sell_grade_pct: null,
          trade_grade_pct: null,
        },
      ],
    })

    renderTradeJournalPanel()
    await waitFor(() => expect(screen.getByText('AAA')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Buy Grade' }))

    const table = screen.getByRole('table', { name: 'Trade journal' })
    const ascendingRows = within(table).getAllByRole('row').slice(1)
    expect(within(ascendingRows[0]).getByText('AAA')).toBeInTheDocument()
    expect(within(ascendingRows[1]).getByText('BBB')).toBeInTheDocument()
    expect(within(ascendingRows[2]).getByText('CCC')).toBeInTheDocument()

    // Descending should still keep the null (CCC) last, not first.
    await user.click(screen.getByRole('button', { name: 'Buy Grade' }))
    const descendingRows = within(table).getAllByRole('row').slice(1)
    expect(within(descendingRows[0]).getByText('BBB')).toBeInTheDocument()
    expect(within(descendingRows[1]).getByText('AAA')).toBeInTheDocument()
    expect(within(descendingRows[2]).getByText('CCC')).toBeInTheDocument()
  })

  it('wires each grade cell’s MetricHelp to its own formula/value explanation', async () => {
    const user = userEvent.setup()
    mockClosedTrades({
      items: [
        {
          id: 'trade_abc123',
          ticker: 'ADSK',
          quantity: 100,
          entry_price: 51.77,
          entry_date: '2026-03-02',
          exit_price: 53.78,
          exit_date: '2026-03-09',
          realized_pnl: 201.0,
          exit_reason: 'target_hit',
          buy_grade_pct: 97.3,
          sell_grade_pct: 35.5,
          trade_grade_pct: 32.1,
        },
      ],
    })

    renderTradeJournalPanel()
    await waitFor(() => expect(screen.getByText('ADSK')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Sell Grade help' }))
    expect(
      screen.getByText(
        'You sold at 35.5% up the exit day’s high-low range -- Elder considers a sell grade over 50% "very good".',
      ),
    ).toBeInTheDocument()
    await user.keyboard('{Escape}')

    await user.click(screen.getByRole('button', { name: 'Trade Grade help' }))
    expect(
      screen.getByText(
        'This trade captured 32.1% of the entry day’s channel height -- Elder rates roughly 30%+ capture an "A" trade, and around 10% a "C" trade.',
      ),
    ).toBeInTheDocument()
  })

  it('renders an em dash plus a "not available" explanation for null grade fields', async () => {
    const user = userEvent.setup()
    mockClosedTrades({
      items: [
        {
          id: 'trade_def456',
          ticker: 'TSLA',
          quantity: 5,
          entry_price: 210.0,
          entry_date: '2026-01-15',
          exit_price: 195.0,
          exit_date: '2026-01-22',
          realized_pnl: -75.0,
          exit_reason: 'stop_hit',
          buy_grade_pct: null,
          sell_grade_pct: null,
          trade_grade_pct: null,
        },
      ],
    })

    renderTradeJournalPanel()
    await waitFor(() => expect(screen.getByText('TSLA')).toBeInTheDocument())

    const row = screen.getByText('TSLA').closest('tr') as HTMLElement
    // 3 null grade cells plus the Notes column's own em dash (no entry_notes
    // on this fixture row).
    expect(within(row).getAllByText('—')).toHaveLength(4)

    const loss = within(row).getByText('-$75.00')
    expect(loss).toHaveStyle({ color: theme.palette.error.main })
    expect(within(row).getByText('Stop hit')).toBeInTheDocument()

    await user.click(within(row).getByRole('button', { name: 'Buy Grade help' }))
    expect(
      screen.getByText(/couldn’t be found in this ticker’s currently-fetchable/),
    ).toBeInTheDocument()

    await user.keyboard('{Escape}')
    await user.click(within(row).getByRole('button', { name: 'Trade Grade help' }))
    expect(screen.getByText(/warm-up window/)).toBeInTheDocument()
  })

  it('shows an em dash with no notes trigger when entry_notes is absent', async () => {
    mockClosedTrades({
      items: [
        {
          id: 'trade_no_notes',
          ticker: 'NFLX',
          quantity: 1,
          entry_price: 100,
          entry_date: '2026-01-01',
          exit_price: 110,
          exit_date: '2026-01-05',
          realized_pnl: 10,
          exit_reason: 'target_hit',
          buy_grade_pct: null,
          sell_grade_pct: null,
          trade_grade_pct: null,
          entry_notes: null,
        },
      ],
    })

    renderTradeJournalPanel()
    await waitFor(() => expect(screen.getByText('NFLX')).toBeInTheDocument())

    const row = screen.getByText('NFLX').closest('tr') as HTMLElement
    expect(
      within(row).queryByRole('button', { name: 'View entry notes' }),
    ).not.toBeInTheDocument()
  })

  it('opens an InfoBalloon with the full entry note when one is present', async () => {
    const user = userEvent.setup()
    mockClosedTrades({
      items: [
        {
          id: 'trade_with_notes',
          ticker: 'GOOG',
          quantity: 1,
          entry_price: 100,
          entry_date: '2026-01-01',
          exit_price: 110,
          exit_date: '2026-01-05',
          realized_pnl: 10,
          exit_reason: 'target_hit',
          buy_grade_pct: null,
          sell_grade_pct: null,
          trade_grade_pct: null,
          entry_notes: 'Breakout above resistance, strong earnings beat.',
        },
      ],
    })

    renderTradeJournalPanel()
    await waitFor(() => expect(screen.getByText('GOOG')).toBeInTheDocument())

    const row = screen.getByText('GOOG').closest('tr') as HTMLElement
    await user.click(within(row).getByRole('button', { name: 'View entry notes' }))

    expect(screen.getByText('Entry Notes')).toBeInTheDocument()
    expect(
      screen.getByText('Breakout above resistance, strong earnings beat.'),
    ).toBeInTheDocument()
  })

  it('falls back to a humanized label for an exit reason not in the known label map', async () => {
    mockClosedTrades({
      items: [
        {
          id: 'trade_xyz',
          ticker: 'AAPL',
          quantity: 1,
          entry_price: 100,
          entry_date: '2026-01-01',
          exit_price: 110,
          exit_date: '2026-01-05',
          realized_pnl: 10,
          // Cast: exercising the same forward-compat fallback
          // humanizeSnakeCase provides for exit_flags/watchlist labels.
          exit_reason: 'some_future_reason' as ClosedTradesResponse['items'][number]['exit_reason'],
          buy_grade_pct: null,
          sell_grade_pct: null,
          trade_grade_pct: null,
        },
      ],
    })

    renderTradeJournalPanel()

    expect(await screen.findByText('Some future reason')).toBeInTheDocument()
  })

  it('shows the empty state when there are no closed trades', async () => {
    mockClosedTrades({ items: [] })

    renderTradeJournalPanel()

    await waitFor(() =>
      expect(screen.getByText('No closed trades yet.')).toBeInTheDocument(),
    )
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows a loading state, then an ApiError via common/ErrorState on failure', async () => {
    server.use(
      http.get('/api/portfolio/closed-trades', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )

    renderTradeJournalPanel()

    expect(screen.getByText('Loading trade journal...')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })
})
