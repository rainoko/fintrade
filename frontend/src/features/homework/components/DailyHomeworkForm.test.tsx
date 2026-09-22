import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { createTestQueryClient, renderWithProviders } from '../../../../tests/renderWithProviders'
import { resetDailyHomeworkStore } from '../../../../tests/mocks/handlers'
import { server } from '../../../../tests/mocks/server'
import DailyHomeworkForm from './DailyHomeworkForm'

async function selectOption(user: ReturnType<typeof userEvent.setup>, label: string, option: string) {
  await user.click(screen.getByRole('combobox', { name: new RegExp(label) }))
  await user.click(await screen.findByRole('option', { name: option }))
}

describe('DailyHomeworkForm', () => {
  beforeEach(() => {
    resetDailyHomeworkStore()
  })

  it('renders every question with the neutral (1) default, prefilling "yesterday" from the suggestion', async () => {
    renderWithProviders(<DailyHomeworkForm />)

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Am I ready to trade today?' })).toBeInTheDocument(),
    )

    expect(screen.getByRole('combobox', { name: /How do I feel physically/ })).toHaveTextContent(
      '1 — Okay',
    )
    expect(screen.getByRole('combobox', { name: /What is my mood/ })).toHaveTextContent(
      '1 — Neutral',
    )
    // Prefilled from the mock suggestion fixture's suggested_score: 2 --
    // the suggestion request only starts (enabled-gated) once today's entry
    // query has already settled, so this needs its own wait rather than
    // being available synchronously alongside the fields above.
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: /How did I trade yesterday/ })).toHaveTextContent(
        '2 — Well',
      ),
    )
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
    expect(screen.queryByTestId('homework-score-banner')).not.toBeInTheDocument()
  })

  it('falls back to the neutral default for "yesterday" when the suggestion has no score (nothing closed yesterday)', async () => {
    server.use(
      http.get('/api/daily-homework/yesterday-trading-suggestion', () =>
        HttpResponse.json({ as_of_date: '2026-09-20', net_realized_pnl: null, suggested_score: null }),
      ),
    )

    renderWithProviders(<DailyHomeworkForm />)

    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: /How did I trade yesterday/ })).toBeInTheDocument(),
    )
    expect(screen.getByRole('combobox', { name: /How did I trade yesterday/ })).toHaveTextContent(
      '1 — Neutral / no trades',
    )
  })

  it('falls back to the neutral default for "yesterday" when the suggestion request itself fails', async () => {
    server.use(http.get('/api/daily-homework/yesterday-trading-suggestion', () => HttpResponse.error()))

    renderWithProviders(<DailyHomeworkForm />)

    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: /How did I trade yesterday/ })).toBeInTheDocument(),
    )
    expect(screen.getByRole('combobox', { name: /How did I trade yesterday/ })).toHaveTextContent(
      '1 — Neutral / no trades',
    )
  })

  it('submits the five answers and shows the resulting color-coded score band', async () => {
    const user = userEvent.setup()
    renderWithProviders(<DailyHomeworkForm />)

    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: /How do I feel physically/ })).toBeInTheDocument(),
    )
    // yesterday_trading_score's prefill only starts (enabled-gated) once
    // today's entry query has already settled, so wait for it to land at
    // its suggested value before relying on it below.
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: /How did I trade yesterday/ })).toHaveTextContent(
        '2 — Well',
      ),
    )

    await selectOption(user, 'How do I feel physically', '2 — Good')
    await selectOption(user, 'Have I done my trade planning', '2 — Fully')
    await selectOption(user, 'What is my mood', '2 — Good')
    await selectOption(user, 'How busy is my schedule today', '2 — Clear')
    // yesterday_trading_score stays at its prefilled 2 -- total 10.
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(screen.getByTestId('homework-score-banner')).toBeInTheDocument())
    expect(screen.getByText('10/10 -- YELLOW (too perfect)')).toBeInTheDocument()
    expect(
      screen.getByText(/any change is bound to be for the worse/i),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Update' })).toBeInTheDocument()
  })

  it('submitting a red-band score shows the "don\'t trade" message', async () => {
    const user = userEvent.setup()
    renderWithProviders(<DailyHomeworkForm />)

    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: /How do I feel physically/ })).toBeInTheDocument(),
    )

    await selectOption(user, 'How do I feel physically', '0 — Poor')
    await selectOption(user, 'How did I trade yesterday', '0 — Poorly')
    await selectOption(user, 'Have I done my trade planning', '0 — No')
    await selectOption(user, 'What is my mood', '0 — Poor')
    await selectOption(user, 'How busy is my schedule today', '0 — Very busy')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(screen.getByTestId('homework-score-banner')).toBeInTheDocument())
    expect(screen.getByText('0/10 -- RED')).toBeInTheDocument()
    expect(screen.getByText("Don't trade today.")).toBeInTheDocument()
  })

  it('loads an already-recorded entry for today and pre-fills the form from it', async () => {
    server.use(
      http.get('/api/daily-homework/today', () =>
        HttpResponse.json({
          entry: {
            date: '2026-09-22',
            physical_state_score: 2,
            yesterday_trading_score: 1,
            trade_planning_score: 2,
            mood_score: 2,
            schedule_score: 1,
            total_score: 8,
            band: 'green',
            recorded_at: '2026-09-22T13:00:00Z',
          },
        }),
      ),
    )

    renderWithProviders(<DailyHomeworkForm />)

    await waitFor(() => expect(screen.getByTestId('homework-score-banner')).toBeInTheDocument())
    expect(screen.getByText('8/10 -- GREEN')).toBeInTheDocument()
    expect(screen.getByText('Good to trade.')).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: /How do I feel physically/ })).toHaveTextContent(
      '2 — Good',
    )
    // An existing entry is the user's own true answer for "yesterday" --
    // never silently replaced by the suggestion fixture's own value (2).
    expect(screen.getByRole('combobox', { name: /How did I trade yesterday/ })).toHaveTextContent(
      '1 — Neutral',
    )
    expect(screen.getByRole('button', { name: 'Update' })).toBeInTheDocument()
  })

  it('renders the form as soon as today\'s entry settles, without waiting on a slow suggestion request (frontend-daily-homework-page-followups)', async () => {
    server.use(
      http.get('/api/daily-homework/yesterday-trading-suggestion', async () => {
        await delay('infinite')
        return HttpResponse.json({
          as_of_date: '2026-09-20',
          net_realized_pnl: 150.0,
          suggested_score: 2,
        })
      }),
    )

    renderWithProviders(<DailyHomeworkForm />)

    // The other four questions render immediately once today's entry query
    // settles, even though the suggestion request never resolves.
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: /How do I feel physically/ })).toBeInTheDocument(),
    )
    // The one field the (still-pending) suggestion would have prefilled
    // falls back to the neutral default rather than blocking on it.
    expect(screen.getByRole('combobox', { name: /How did I trade yesterday/ })).toHaveTextContent(
      '1 — Neutral / no trades',
    )
  })

  it('does not wait on the suggestion request at all when today\'s entry already exists (frontend-daily-homework-page-followups)', async () => {
    server.use(
      http.get('/api/daily-homework/today', () =>
        HttpResponse.json({
          entry: {
            date: '2026-09-22',
            physical_state_score: 2,
            yesterday_trading_score: 1,
            trade_planning_score: 2,
            mood_score: 2,
            schedule_score: 1,
            total_score: 8,
            band: 'green',
            recorded_at: '2026-09-22T13:00:00Z',
          },
        }),
      ),
      http.get('/api/daily-homework/yesterday-trading-suggestion', async () => {
        await delay('infinite')
        return HttpResponse.json({
          as_of_date: '2026-09-20',
          net_realized_pnl: 150.0,
          suggested_score: 2,
        })
      }),
    )

    renderWithProviders(<DailyHomeworkForm />)

    await waitFor(() => expect(screen.getByTestId('homework-score-banner')).toBeInTheDocument())
    expect(screen.getByText('8/10 -- GREEN')).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: /How did I trade yesterday/ })).toHaveTextContent(
      '1 — Neutral',
    )
  })

  it(
    'does not re-dispatch the suggestion request on a warm remount where today\'s entry is ' +
      'already cached from a previous load (frontend-daily-homework-page-followups-followups)',
    async () => {
      let suggestionRequestCount = 0
      server.use(
        http.get('/api/daily-homework/today', () =>
          HttpResponse.json({
            entry: {
              date: '2026-09-22',
              physical_state_score: 2,
              yesterday_trading_score: 1,
              trade_planning_score: 2,
              mood_score: 2,
              schedule_score: 1,
              total_score: 8,
              band: 'green',
              recorded_at: '2026-09-22T13:00:00Z',
            },
          }),
        ),
        http.get('/api/daily-homework/yesterday-trading-suggestion', () => {
          suggestionRequestCount += 1
          return HttpResponse.json({
            as_of_date: '2026-09-20',
            net_realized_pnl: 150.0,
            suggested_score: 2,
          })
        }),
      )

      // A shared QueryClient across both mounts, so the second mount's
      // `useDailyHomeworkToday` call is served synchronously from the
      // already-cached (non-null) `entry` rather than starting `isLoading`
      // again -- exactly the "revisit within the same session after already
      // submitting today's entry" case the `enabled` gate is meant to help
      // with (`useYesterdayTradingSuggestion`'s `enabled` is `false` from
      // this second mount's very first render, since `existingEntry` is
      // already known then, not just once a fresh fetch settles).
      const queryClient = createTestQueryClient()
      const { unmount } = renderWithProviders(<DailyHomeworkForm />, { queryClient })
      await waitFor(() => expect(screen.getByTestId('homework-score-banner')).toBeInTheDocument())
      expect(suggestionRequestCount).toBe(1)

      unmount()
      renderWithProviders(<DailyHomeworkForm />, { queryClient })
      await waitFor(() => expect(screen.getByTestId('homework-score-banner')).toBeInTheDocument())
      // Give a would-be (wrongly re-enabled) request a chance to have fired.
      await new Promise((resolve) => setTimeout(resolve, 10))
      expect(suggestionRequestCount).toBe(1)
    },
  )

  it('shows an ApiError via common/ErrorState when loading today\'s entry fails', async () => {
    server.use(http.get('/api/daily-homework/today', () => HttpResponse.error()))

    renderWithProviders(<DailyHomeworkForm />)

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })

  it('shows an ApiError via common/ErrorState when submitting fails', async () => {
    const user = userEvent.setup()
    renderWithProviders(<DailyHomeworkForm />)

    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: /How do I feel physically/ })).toBeInTheDocument(),
    )

    server.use(http.post('/api/daily-homework', () => HttpResponse.error()))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })
})
