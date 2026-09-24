import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { createTestQueryClient, renderWithProviders } from '../../../../tests/renderWithProviders'
import { resetDailyHomeworkStore } from '../../../../tests/mocks/handlers'
import { server } from '../../../../tests/mocks/server'
import { homeworkKeys } from '../hooks/queryKeys'
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
    // A request-count wait, not just a text assertion: the neutral default
    // this test expects is the *same* text shown before the suggestion has
    // even resolved, so a plain `waitFor` on that text alone would pass
    // trivially without ever actually exercising the "resolved successfully
    // but with a null score" code path this test means to cover.
    let suggestionRequestCount = 0
    server.use(
      http.get('/api/daily-homework/yesterday-trading-suggestion', () => {
        suggestionRequestCount += 1
        return HttpResponse.json({
          as_of_date: '2026-09-20',
          net_realized_pnl: null,
          suggested_score: null,
        })
      }),
    )

    const queryClient = createTestQueryClient()
    renderWithProviders(<DailyHomeworkForm />, { queryClient })

    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: /How did I trade yesterday/ })).toBeInTheDocument(),
    )
    await waitFor(() => expect(suggestionRequestCount).toBe(1))
    // Wait on the query's own settled status (not just the request having
    // been dispatched) so this also covers DailyHomeworkForm's re-render
    // (and HomeworkQuestionsForm's render-time state adjustment) that
    // follows it settling, without a fixed sleep standing in for that wait.
    await waitFor(() =>
      expect(queryClient.getQueryState(homeworkKeys.yesterdaySuggestion)?.status).toBe('success'),
    )
    expect(screen.getByRole('combobox', { name: /How did I trade yesterday/ })).toHaveTextContent(
      '1 — Neutral / no trades',
    )
  })

  it('falls back to the neutral default for "yesterday" when the suggestion request itself fails', async () => {
    // Same request-count wait as above, for the same reason (the expected
    // text here also matches the pre-resolution default).
    let suggestionRequestCount = 0
    server.use(
      http.get('/api/daily-homework/yesterday-trading-suggestion', () => {
        suggestionRequestCount += 1
        return HttpResponse.error()
      }),
    )

    const queryClient = createTestQueryClient()
    renderWithProviders(<DailyHomeworkForm />, { queryClient })

    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: /How did I trade yesterday/ })).toBeInTheDocument(),
    )
    await waitFor(() => expect(suggestionRequestCount).toBe(1))
    // Wait on the query's own settled (errored) status, same reasoning as
    // the success case above.
    await waitFor(() =>
      expect(queryClient.getQueryState(homeworkKeys.yesterdaySuggestion)?.status).toBe('error'),
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
    'never dispatches the yesterday-trading-suggestion request at all on a cold load when ' +
      "today's entry already exists (frontend-daily-homework-page-followups-followups): the " +
      'query is gated on `todayQuery.isSuccess && !existingEntry`, not a bare `!existingEntry` ' +
      "(which is falsy -- so the gate is `true` -- from the very first render, before today's " +
      'entry query has had any chance to resolve)',
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

      // A fresh, uncached QueryClient each mount (the default from
      // `renderWithProviders`) -- this is deliberately the *cold* load case,
      // not the warm-remount case: `existingEntry` is unknown (`null`) at
      // this component's very first render and only becomes known once
      // `todayQuery` resolves.
      renderWithProviders(<DailyHomeworkForm />)
      await waitFor(() => expect(screen.getByTestId('homework-score-banner')).toBeInTheDocument())
      // Give a would-be (wrongly enabled) request a chance to have fired.
      await new Promise((resolve) => setTimeout(resolve, 20))
      expect(suggestionRequestCount).toBe(0)
    },
  )

  it(
    'prefills "yesterday" once the suggestion resolves after the form has already rendered, ' +
      'for a genuinely new entry, without blocking that initial render on it ' +
      '(frontend-daily-homework-page-followups-followups)',
    async () => {
      // A one-slot holder (rather than a plain reassigned `let`) for the
      // pending request's own `resolve` callback -- keeps TypeScript's
      // control-flow narrowing (which otherwise treats a `let` reassigned
      // only from inside a nested closure as staying at its initial `null`
      // type) out of the way, while still letting the test manually decide
      // exactly when the suggestion request settles.
      const resolvers: Array<() => void> = []
      server.use(
        http.get(
          '/api/daily-homework/yesterday-trading-suggestion',
          () =>
            new Promise<Response>((resolve) => {
              resolvers.push(() =>
                resolve(
                  HttpResponse.json({
                    as_of_date: '2026-09-20',
                    net_realized_pnl: 150.0,
                    suggested_score: 2,
                  }),
                ),
              )
            }),
        ),
      )

      renderWithProviders(<DailyHomeworkForm />)

      // The form (including the field the suggestion would eventually
      // prefill) renders immediately at the neutral default, without
      // blocking on the still-pending suggestion request.
      await waitFor(() =>
        expect(
          screen.getByRole('combobox', { name: /How do I feel physically/ }),
        ).toBeInTheDocument(),
      )
      expect(screen.getByRole('combobox', { name: /How did I trade yesterday/ })).toHaveTextContent(
        '1 — Neutral / no trades',
      )

      // Once the suggestion resolves (after the form has already been
      // showing the neutral default for a while), the field switches
      // in-place to the suggested value via HomeworkQuestionsForm's
      // render-time state adjustment.
      await waitFor(() => expect(resolvers).toHaveLength(1))
      resolvers[0]()
      await waitFor(() =>
        expect(screen.getByRole('combobox', { name: /How did I trade yesterday/ })).toHaveTextContent(
          '2 — Well',
        ),
      )
    },
  )

  it(
    "does not overwrite a user's own answer to \"yesterday\" if the suggestion resolves after " +
      'they have already changed it themselves (frontend-daily-homework-page-followups-followups)',
    async () => {
      const user = userEvent.setup()
      // See the previous test's comment for why this is an array holder
      // rather than a reassigned `let`.
      const resolvers: Array<() => void> = []
      server.use(
        http.get(
          '/api/daily-homework/yesterday-trading-suggestion',
          () =>
            new Promise<Response>((resolve) => {
              resolvers.push(() =>
                resolve(
                  HttpResponse.json({
                    as_of_date: '2026-09-20',
                    net_realized_pnl: 150.0,
                    suggested_score: 2,
                  }),
                ),
              )
            }),
        ),
      )

      const queryClient = createTestQueryClient()
      renderWithProviders(<DailyHomeworkForm />, { queryClient })

      await waitFor(() =>
        expect(
          screen.getByRole('combobox', { name: /How do I feel physically/ }),
        ).toBeInTheDocument(),
      )

      // The user answers "yesterday" themselves (0 -- Poorly) before the
      // suggestion (2 -- Well) has resolved.
      await selectOption(user, 'How did I trade yesterday', '0 — Poorly')
      expect(screen.getByRole('combobox', { name: /How did I trade yesterday/ })).toHaveTextContent(
        '0 — Poorly',
      )

      // The suggestion resolving afterwards must not clobber that answer.
      await waitFor(() => expect(resolvers).toHaveLength(1))
      resolvers[0]()
      // Wait on the query's own settled status (not a fixed sleep) so this
      // genuinely covers the now-resolved suggestion's render-time
      // adjustment having had a chance to run before asserting it didn't
      // clobber the user's own answer.
      await waitFor(() =>
        expect(queryClient.getQueryState(homeworkKeys.yesterdaySuggestion)?.status).toBe('success'),
      )
      expect(screen.getByRole('combobox', { name: /How did I trade yesterday/ })).toHaveTextContent(
        '0 — Poorly',
      )
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
