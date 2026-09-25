import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { resetTradingModeStore } from '../../../../tests/mocks/handlers'
import { createTestQueryClient, renderWithProviders } from '../../../../tests/renderWithProviders'
import { server } from '../../../../tests/mocks/server'
import TradingModeSettingsForm from './TradingModeSettingsForm'

describe('TradingModeSettingsForm', () => {
  beforeEach(() => {
    resetTradingModeStore()
  })

  it('defaults to swing mode with no timeframe-triple fields shown', async () => {
    renderWithProviders(<TradingModeSettingsForm />)

    await waitFor(() =>
      expect(screen.getByRole('radio', { name: /swing/i })).toBeChecked(),
    )
    expect(screen.queryByLabelText(/long-term/i)).not.toBeInTheDocument()
  })

  it('shows an ApiError via common/ErrorState when loading the setting fails', async () => {
    server.use(http.get('/api/settings/trading-mode', () => HttpResponse.error()))

    renderWithProviders(<TradingModeSettingsForm />)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })

  it('selecting Day Trader reveals the three timeframe-triple leg fields', async () => {
    const user = userEvent.setup()
    renderWithProviders(<TradingModeSettingsForm />)

    await waitFor(() => expect(screen.getByRole('radio', { name: /swing/i })).toBeChecked())
    await user.click(screen.getByRole('radio', { name: /day trader/i }))

    expect(screen.getByLabelText(/long-term/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/intermediate/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/short-term/i)).toBeInTheDocument()
  })

  it('blocks submission client-side when a day-trader leg is left blank', async () => {
    const user = userEvent.setup()
    renderWithProviders(<TradingModeSettingsForm />)

    await waitFor(() => expect(screen.getByRole('radio', { name: /swing/i })).toBeChecked())
    await user.click(screen.getByRole('radio', { name: /day trader/i }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findAllByText('Required.')).toHaveLength(3)
    expect(screen.queryByText('Trading mode saved.')).not.toBeInTheDocument()
  })

  it('blocks submission client-side when a leg does not match the interval-code pattern', async () => {
    const user = userEvent.setup()
    renderWithProviders(<TradingModeSettingsForm />)

    await waitFor(() => expect(screen.getByRole('radio', { name: /swing/i })).toBeChecked())
    await user.click(screen.getByRole('radio', { name: /day trader/i }))

    await user.type(screen.getByLabelText(/long-term/i), '25 minutes')
    await user.type(screen.getByLabelText(/intermediate/i), '5m')
    await user.type(screen.getByLabelText(/short-term/i), '2m')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(
      await screen.findByText(/must be a positive whole number/i),
    ).toBeInTheDocument()
    expect(screen.queryByText('Trading mode saved.')).not.toBeInTheDocument()
  })

  it('submits a valid day-trader triple and shows a success message', async () => {
    const user = userEvent.setup()
    renderWithProviders(<TradingModeSettingsForm />)

    await waitFor(() => expect(screen.getByRole('radio', { name: /swing/i })).toBeChecked())
    await user.click(screen.getByRole('radio', { name: /day trader/i }))

    await user.type(screen.getByLabelText(/long-term/i), '25m')
    await user.type(screen.getByLabelText(/intermediate/i), '5m')
    await user.type(screen.getByLabelText(/short-term/i), '2m')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(screen.getByText('Trading mode saved.')).toBeInTheDocument())
  })

  it('shows non-blocking factor-of-five warnings from the response without blocking the save', async () => {
    const user = userEvent.setup()
    renderWithProviders(<TradingModeSettingsForm />)

    await waitFor(() => expect(screen.getByRole('radio', { name: /swing/i })).toBeChecked())
    await user.click(screen.getByRole('radio', { name: /day trader/i }))

    // 10m/9m is far outside the factor-of-five guideline band, but still a
    // well-formed, correctly-ordered triple -- the mock server's own
    // factor_of_five_warnings computation (see tests/mocks/handlers.ts)
    // returns a non-empty warning list for it, but 200s regardless.
    await user.type(screen.getByLabelText(/long-term/i), '10m')
    await user.type(screen.getByLabelText(/intermediate/i), '9m')
    await user.type(screen.getByLabelText(/short-term/i), '1m')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(screen.getByText('Trading mode saved.')).toBeInTheDocument())
    expect(screen.getByText(/falls outside ch\. 39's roughly-factor-of-five/i)).toBeInTheDocument()
  })

  it('surfaces the backend 422 (ordering violation) via common/ErrorState', async () => {
    const user = userEvent.setup()
    renderWithProviders(<TradingModeSettingsForm />)

    await waitFor(() => expect(screen.getByRole('radio', { name: /swing/i })).toBeChecked())
    await user.click(screen.getByRole('radio', { name: /day trader/i }))

    // Passes client-side format validation (each leg matches the interval
    // code pattern) but violates the backend's strictly-decreasing ordering
    // rule -- exercises the 422 this form deliberately leaves to the
    // backend rather than re-validating client-side (this task's
    // `decisions` entry).
    await user.type(screen.getByLabelText(/long-term/i), '2m')
    await user.type(screen.getByLabelText(/intermediate/i), '5m')
    await user.type(screen.getByLabelText(/short-term/i), '25m')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })

  it('pre-fills the triple fields with an already-persisted configuration', async () => {
    server.use(
      http.get('/api/settings/trading-mode', () =>
        HttpResponse.json({
          mode: 'day_trader',
          day_trader_timeframe_triple: {
            long_term: '25m',
            intermediate: '5m',
            short_term: '2m',
            factor_of_five_warnings: [],
          },
        }),
      ),
    )

    renderWithProviders(<TradingModeSettingsForm />)

    await waitFor(() => expect(screen.getByRole('radio', { name: /day trader/i })).toBeChecked())
    expect(screen.getByLabelText(/long-term/i)).toHaveValue('25m')
    expect(screen.getByLabelText(/intermediate/i)).toHaveValue('5m')
    expect(screen.getByLabelText(/short-term/i)).toHaveValue('2m')
  })

  it('switching back to swing mode does not require the triple fields', async () => {
    server.use(
      http.get('/api/settings/trading-mode', () =>
        HttpResponse.json({
          mode: 'day_trader',
          day_trader_timeframe_triple: {
            long_term: '25m',
            intermediate: '5m',
            short_term: '2m',
            factor_of_five_warnings: [],
          },
        }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<TradingModeSettingsForm />)

    await waitFor(() => expect(screen.getByRole('radio', { name: /day trader/i })).toBeChecked())
    // Clear one leg to an otherwise-invalid (blank) value first -- proves
    // the swing branch below doesn't validate the (now-hidden) triple
    // fields at all, rather than merely happening to pass because they
    // were still populated with a valid pre-filled value.
    await user.clear(screen.getByLabelText(/intermediate/i))
    await user.click(screen.getByRole('radio', { name: /swing/i }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(screen.getByText('Trading mode saved.')).toBeInTheDocument())
  })

  it('clears a stale validation error on a leg as the user corrects it, without resubmitting', async () => {
    const user = userEvent.setup()
    renderWithProviders(<TradingModeSettingsForm />)

    await waitFor(() => expect(screen.getByRole('radio', { name: /swing/i })).toBeChecked())
    await user.click(screen.getByRole('radio', { name: /day trader/i }))

    await user.type(screen.getByLabelText(/long-term/i), 'abc')
    await user.type(screen.getByLabelText(/intermediate/i), '5m')
    await user.type(screen.getByLabelText(/short-term/i), '2m')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText(/must be a positive whole number/i)).toBeInTheDocument()

    // Correct the invalid leg without clicking Save again -- the stale
    // error/helper text should disappear immediately as the field is
    // edited, not linger until the next submit (PR #327's review finding,
    // this task's checklist item 1).
    await user.clear(screen.getByLabelText(/long-term/i))
    await user.type(screen.getByLabelText(/long-term/i), '25m')

    expect(screen.queryByText(/must be a positive whole number/i)).not.toBeInTheDocument()
  })

  it('clears stale validation errors when toggling the mode radio', async () => {
    const user = userEvent.setup()
    renderWithProviders(<TradingModeSettingsForm />)

    await waitFor(() => expect(screen.getByRole('radio', { name: /swing/i })).toBeChecked())
    await user.click(screen.getByRole('radio', { name: /day trader/i }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findAllByText('Required.')).toHaveLength(3)

    // Toggle away and back to Day Trader without fixing anything -- the
    // previous attempt's stale "Required." errors should not reappear
    // before any new edit or submit (this task's checklist item 1).
    await user.click(screen.getByRole('radio', { name: /swing/i }))
    await user.click(screen.getByRole('radio', { name: /day trader/i }))

    expect(screen.queryByText('Required.')).not.toBeInTheDocument()
  })

  it('invalidates only the stocks/watchlist/portfolio query-key prefixes on a successful save, not every cached query', async () => {
    const queryClient = createTestQueryClient()
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    const user = userEvent.setup()
    renderWithProviders(<TradingModeSettingsForm />, { queryClient })

    await waitFor(() => expect(screen.getByRole('radio', { name: /swing/i })).toBeChecked())
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(screen.getByText('Trading mode saved.')).toBeInTheDocument())

    expect(invalidateSpy).toHaveBeenCalledTimes(3)
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['stocks'] })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['watchlist'] })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['portfolio'] })
    // Never called unfiltered (the app-wide blanket this task's checklist
    // item replaced).
    expect(invalidateSpy).not.toHaveBeenCalledWith()
  })

  it('clears a stale success/error message once the user edits a field again', async () => {
    const user = userEvent.setup()
    renderWithProviders(<TradingModeSettingsForm />)

    await waitFor(() => expect(screen.getByRole('radio', { name: /swing/i })).toBeChecked())
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(screen.getByText('Trading mode saved.')).toBeInTheDocument())

    await user.click(screen.getByRole('radio', { name: /day trader/i }))

    expect(screen.queryByText('Trading mode saved.')).not.toBeInTheDocument()
  })
})
