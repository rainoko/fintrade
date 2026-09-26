import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import TradeApgarDialog from './TradeApgarDialog'

async function selectOption(user: ReturnType<typeof userEvent.setup>, label: string, option: string) {
  await user.click(screen.getByRole('combobox', { name: new RegExp(label) }))
  await user.click(await screen.findByRole('option', { name: option }))
}

describe('TradeApgarDialog', () => {
  it('renders nothing when ticker is null', () => {
    renderWithProviders(<TradeApgarDialog ticker={null} onClose={vi.fn()} />)

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows the ticker in the title', () => {
    renderWithProviders(<TradeApgarDialog ticker="AAPL" onClose={vi.fn()} />)

    expect(screen.getByText('Trade Apgar: AAPL')).toBeInTheDocument()
  })

  it('calls onClose when Close is clicked', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    renderWithProviders(<TradeApgarDialog ticker="AAPL" onClose={onClose} />)

    await user.click(screen.getByRole('button', { name: 'Close' }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('scores a GO outcome (total >= 7, no single zero)', async () => {
    const user = userEvent.setup()
    renderWithProviders(<TradeApgarDialog ticker="AAPL" onClose={vi.fn()} />)

    await selectOption(user, 'False breakout status', 'On the verge')
    await selectOption(user, '"Perfection"', 'Both timeframes look ideal')
    await user.click(screen.getByRole('button', { name: 'Score' }))

    await waitFor(() => expect(screen.getByText(/GO —/)).toBeInTheDocument())
    expect(screen.getByText('GO — total score 7/10')).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Trade Apgar questions' })
    expect(within(table).getByText('Weekly Impulse')).toBeInTheDocument()
    expect(within(table).getByText('"Perfection" (both timeframes look ideal)')).toBeInTheDocument()
    // Value column renders humanized/friendly text, not the raw API value --
    // the two auto Impulse questions ('GREEN') fall back to
    // humanizeSnakeCase's generic capitalization, 'in_value_zone' likewise,
    // and the two manual questions ('on_the_verge'/'both') reuse this
    // dialog's own FALSE_BREAKOUT_OPTIONS/PERFECTION_OPTIONS label maps
    // (frontend-trade-apgar-followups).
    expect(within(table).getAllByText('Green')).toHaveLength(2)
    expect(within(table).queryByText('GREEN')).not.toBeInTheDocument()
    expect(within(table).getByText('In value zone')).toBeInTheDocument()
    expect(within(table).getByText('On the verge')).toBeInTheDocument()
    expect(within(table).getByText('Both timeframes look ideal')).toBeInTheDocument()
  })

  it('scores a NO-GO outcome from a low total (no single zero)', async () => {
    const user = userEvent.setup()
    renderWithProviders(<TradeApgarDialog ticker="AAPL" onClose={vi.fn()} />)

    await selectOption(user, 'False breakout status', 'Already happened')
    await selectOption(user, '"Perfection"', 'One timeframe looks ideal')
    await user.click(screen.getByRole('button', { name: 'Score' }))

    await waitFor(() => expect(screen.getByText(/NO-GO —/)).toBeInTheDocument())
    expect(screen.getByText('NO-GO — total score 5/10')).toBeInTheDocument()
    // Low-total no-go, not the single-zero rule -- no additional explanatory
    // note about the "no single zero" carve-out should be shown.
    expect(
      screen.queryByText(/Elder's "no single zero" rule still blocks this trade/),
    ).not.toBeInTheDocument()
  })

  it('scores a NO-GO outcome from a single zero despite a high total', async () => {
    const user = userEvent.setup()
    renderWithProviders(<TradeApgarDialog ticker="APGARHIGH" onClose={vi.fn()} />)

    await selectOption(user, 'False breakout status', 'On the verge')
    // perfection stays at its default 'neither' (score 0)
    await user.click(screen.getByRole('button', { name: 'Score' }))

    await waitFor(() => expect(screen.getByText(/NO-GO —/)).toBeInTheDocument())
    expect(screen.getByText('NO-GO — total score 8/10')).toBeInTheDocument()
    expect(
      screen.getByText(/Elder's "no single zero" rule still blocks this trade/),
    ).toBeInTheDocument()
    // APGARHIGH's auto questions are BLUE/BLUE/below_value -- humanized via
    // the same VALUE_LABELS fallback as the GO test's GREEN/in_value_zone.
    const table = screen.getByRole('table', { name: 'Trade Apgar questions' })
    expect(within(table).getAllByText('Blue')).toHaveLength(2)
    expect(within(table).getByText('Below value')).toBeInTheDocument()
  })

  it('shows an ApiError via common/ErrorState for an unknown ticker', async () => {
    const user = userEvent.setup()
    renderWithProviders(<TradeApgarDialog ticker="UNKNOWN" onClose={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: 'Score' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })

  it('resets manual answers and results when switching to a different ticker', async () => {
    const user = userEvent.setup()
    const { rerender } = renderWithProviders(<TradeApgarDialog ticker="AAPL" onClose={vi.fn()} />)

    await selectOption(user, 'False breakout status', 'On the verge')
    await user.click(screen.getByRole('button', { name: 'Score' }))
    await waitFor(() => expect(screen.getByText(/GO —|NO-GO —/)).toBeInTheDocument())

    rerender(<TradeApgarDialog ticker="MSFT" onClose={vi.fn()} />)

    expect(screen.getByText('Trade Apgar: MSFT')).toBeInTheDocument()
    expect(screen.queryByText(/GO —|NO-GO —/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Score' })).toBeInTheDocument()
  })

  it('closes when the ticker prop transitions to null', async () => {
    const { rerender } = renderWithProviders(<TradeApgarDialog ticker="AAPL" onClose={vi.fn()} />)
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    rerender(<TradeApgarDialog ticker={null} onClose={vi.fn()} />)

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  // frontend-ibkr-portfolio-preload-followups-followups-followups: MUI's
  // Dialog fires its own onClose on Escape regardless of any button's own
  // disabled state -- only guarding the Close button isn't enough (same gap
  // AddPositionDialog/IbkrPreloadDialog had, fixed there first).
  it('does not let Escape dismiss the dialog while the trade-apgar mutation is pending', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    server.use(
      http.post('/api/portfolio/trade-apgar', async () => {
        await delay('infinite')
        return HttpResponse.json({})
      }),
    )
    renderWithProviders(<TradeApgarDialog ticker="AAPL" onClose={onClose} />)

    await user.click(screen.getByRole('button', { name: 'Score' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Close' })).toBeDisabled())
    // Dispatched directly on the dialog itself (fireEvent, not
    // userEvent.keyboard): once the submit button is disabled by the
    // pending mutation's loading state, the browser blurs it, moving
    // `document.activeElement` outside the modal -- userEvent.keyboard()
    // dispatches to `document.activeElement`, which would then never reach
    // MUI's Modal keydown handler at all, making this assertion pass
    // vacuously regardless of whether the guard actually works.
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape', code: 'Escape' })

    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('lets Escape dismiss the dialog normally once no mutation is pending', () => {
    const onClose = vi.fn()
    renderWithProviders(<TradeApgarDialog ticker="AAPL" onClose={onClose} />)

    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape', code: 'Escape' })

    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
