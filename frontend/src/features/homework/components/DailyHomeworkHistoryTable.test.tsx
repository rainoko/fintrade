import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { recordDailyHomework } from '../../../api/homework'
import { resetDailyHomeworkStore } from '../../../../tests/mocks/handlers'
import { server } from '../../../../tests/mocks/server'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import DailyHomeworkHistoryTable from './DailyHomeworkHistoryTable'

describe('DailyHomeworkHistoryTable', () => {
  beforeEach(() => {
    resetDailyHomeworkStore()
  })

  it('shows the empty state when nothing has been recorded yet', async () => {
    renderWithProviders(<DailyHomeworkHistoryTable />)

    expect(screen.getByText('Loading self-test history...')).toBeInTheDocument()

    await waitFor(() =>
      expect(screen.getByText('No self-test entries recorded yet.')).toBeInTheDocument(),
    )
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('lists every recorded entry most-recent-first, with per-row scores and a band chip', async () => {
    // Backfills two past days (a red day and a green day) plus today
    // (yellow, "too perfect") via the real upsert endpoint -- DailyHomeworkIn's
    // optional `date` field lets a caller backfill/correct an earlier day,
    // which this seeds through rather than reaching into the mock store's
    // internals directly.
    await recordDailyHomework({
      date: '2026-09-01',
      physical_state_score: 0,
      yesterday_trading_score: 0,
      trade_planning_score: 1,
      mood_score: 0,
      schedule_score: 1,
    })
    await recordDailyHomework({
      date: '2026-09-15',
      physical_state_score: 2,
      yesterday_trading_score: 2,
      trade_planning_score: 2,
      mood_score: 1,
      schedule_score: 1,
    })
    await recordDailyHomework({
      date: '2026-09-20',
      physical_state_score: 2,
      yesterday_trading_score: 2,
      trade_planning_score: 2,
      mood_score: 2,
      schedule_score: 2,
    })

    renderWithProviders(<DailyHomeworkHistoryTable />)

    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Daily homework history' })).toBeInTheDocument(),
    )

    const rows = screen.getAllByRole('row')
    // Header row + 3 data rows, most-recent date first.
    expect(rows).toHaveLength(4)
    expect(within(rows[1]).getByText('Sep 20, 2026')).toBeInTheDocument()
    expect(within(rows[1]).getByText('10')).toBeInTheDocument()
    expect(within(rows[1]).getByText('YELLOW (TOO PERFECT)')).toBeInTheDocument()

    expect(within(rows[2]).getByText('Sep 15, 2026')).toBeInTheDocument()
    expect(within(rows[2]).getByText('8')).toBeInTheDocument()
    expect(within(rows[2]).getByText('GREEN')).toBeInTheDocument()

    expect(within(rows[3]).getByText('Sep 1, 2026')).toBeInTheDocument()
    expect(within(rows[3]).getByText('2')).toBeInTheDocument()
    expect(within(rows[3]).getByText('RED')).toBeInTheDocument()
  })

  it('shows a loading state, then an ApiError via common/ErrorState on failure', async () => {
    server.use(
      http.get('/api/daily-homework', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )

    renderWithProviders(<DailyHomeworkHistoryTable />)

    expect(screen.getByText('Loading self-test history...')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })
})
