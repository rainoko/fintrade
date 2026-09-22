import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { server } from '../../tests/mocks/server'
import { resetPortfolioStore } from '../../tests/mocks/handlers'
import {
  addPosition,
  deletePosition,
  getClosedTrades,
  getPortfolio,
  getPortfolioRisk,
  recordFollowUpReview,
} from './portfolio'

describe('api/portfolio', () => {
  beforeEach(() => {
    resetPortfolioStore()
  })

  it('getPortfolio returns equity and positions', async () => {
    const portfolio = await getPortfolio()

    expect(portfolio.equity.total).toBe(
      portfolio.equity.cash + portfolio.equity.positions_value,
    )
    expect(portfolio.positions).toHaveLength(1)
    expect(portfolio.positions[0]?.ticker).toBe('AAPL')
  })

  it('getPortfolioRisk returns the 2%/6% rule evaluation', async () => {
    const risk = await getPortfolioRisk()

    expect(risk.six_percent_rule_breached).toBe(false)
    expect(risk.positions[0]?.ticker).toBe('AAPL')
  })

  it('addPosition creates a new position for a ticker not already held', async () => {
    const created = await addPosition({
      ticker: 'MSFT',
      quantity: 10,
      avg_cost_basis: 400,
      entry_date: '2026-01-01',
    })

    expect(created.ticker).toBe('MSFT')
    expect(created.current_price).toBeNull()
    expect(created.unrealized_pnl_pct).toBeNull()

    const portfolio = await getPortfolio()
    expect(portfolio.positions.map((position) => position.ticker)).toContain('MSFT')
  })

  it('addPosition merges into an existing position for the same ticker (quantity-weighted average cost)', async () => {
    // Seeded position: AAPL, quantity 100 @ 195.30, entry_date 2026-05-14.
    const merged = await addPosition({
      ticker: 'aapl', // lowercase on input — normalized to uppercase, matching the backend.
      quantity: 100,
      avg_cost_basis: 205.3,
      entry_date: '2026-06-01',
    })

    expect(merged.id).toBe('pos_123')
    expect(merged.ticker).toBe('AAPL')
    expect(merged.quantity).toBe(200)
    expect(merged.avg_cost_basis).toBeCloseTo(200.3, 5)
    // Earlier of the two entry dates is kept.
    expect(merged.entry_date).toBe('2026-05-14')

    const portfolio = await getPortfolio()
    expect(portfolio.positions).toHaveLength(1)
  })

  it('addPosition rejects a non-positive quantity with a 422 ApiError (HTTPValidationError shape)', async () => {
    await expect(
      addPosition({
        ticker: 'AAPL',
        quantity: 0,
        avg_cost_basis: 100,
        entry_date: '2026-01-01',
      }),
    ).rejects.toMatchObject({ status: 422 })
  })

  it('addPosition reports every invalid field when quantity and avg_cost_basis are both non-positive', async () => {
    const error = await addPosition({
      ticker: 'AAPL',
      quantity: 0,
      avg_cost_basis: -5,
      entry_date: '2026-01-01',
    }).catch((caught: unknown) => caught)

    // client.ts's extractDetail joins every HTTPValidationError entry's msg
    // with '; ' — asserting on the join count (not just "422") is what
    // catches a mock that only ever reports one of the two invalid fields.
    expect(error).toMatchObject({
      status: 422,
      detail: 'Input should be greater than 0; Input should be greater than 0',
    })
  })

  it('addPosition surfaces a merge-overflow 422 ApiError (single ErrorDetail shape)', async () => {
    const error = await addPosition({
      ticker: 'OVERFLOW',
      quantity: 1,
      avg_cost_basis: 1,
      entry_date: '2026-01-01',
    }).catch((caught: unknown) => caught)

    expect(error).toMatchObject({
      status: 422,
      detail: expect.stringContaining('too large'),
    })
  })

  it('addPosition treats a whitespace-padded OVERFLOW ticker as the merge-overflow sentinel too', async () => {
    // Guards the mock's `body.ticker.trim().toUpperCase() === 'OVERFLOW'`
    // check: without trimming, a padded ticker would silently create a real
    // position instead of surfacing the intended 422.
    const error = await addPosition({
      ticker: '  overflow ',
      quantity: 1,
      avg_cost_basis: 1,
      entry_date: '2026-01-01',
    }).catch((caught: unknown) => caught)

    expect(error).toMatchObject({
      status: 422,
      detail: expect.stringContaining('too large'),
    })

    const portfolio = await getPortfolio()
    expect(portfolio.positions.map((position) => position.ticker)).not.toContain(
      'OVERFLOW',
    )
  })

  it('deletePosition removes an existing position', async () => {
    await expect(deletePosition('pos_123')).resolves.toBeUndefined()

    const portfolio = await getPortfolio()
    expect(portfolio.positions).toHaveLength(0)
  })

  it('deletePosition throws a 404 ApiError for an id that does not exist', async () => {
    await expect(deletePosition('does-not-exist')).rejects.toMatchObject({ status: 404 })
  })

  it('deletePosition sends exit_reason as a query param when supplied', async () => {
    let requestedUrl: URL | undefined
    server.use(
      http.delete('/api/portfolio/positions/:id', ({ request }) => {
        requestedUrl = new URL(request.url)
        return new HttpResponse(null, { status: 204 })
      }),
    )

    await deletePosition('pos_123', { exitReason: 'stop_hit' })

    expect(requestedUrl?.searchParams.get('exit_reason')).toBe('stop_hit')
    expect(requestedUrl?.searchParams.has('exit_price')).toBe(false)
    expect(requestedUrl?.searchParams.has('exit_date')).toBe(false)
  })

  it('deletePosition sends no query params at all when none are supplied, preserving the original default request shape', async () => {
    let requestedUrl: URL | undefined
    server.use(
      http.delete('/api/portfolio/positions/:id', ({ request }) => {
        requestedUrl = new URL(request.url)
        return new HttpResponse(null, { status: 204 })
      }),
    )

    await deletePosition('pos_123')

    expect(requestedUrl?.search).toBe('')
  })

  it('deletePosition sends exit_price/exit_date together for a manual-exit override', async () => {
    let requestedUrl: URL | undefined
    server.use(
      http.delete('/api/portfolio/positions/:id', ({ request }) => {
        requestedUrl = new URL(request.url)
        return new HttpResponse(null, { status: 204 })
      }),
    )

    await deletePosition('pos_123', {
      exitReason: 'target_hit',
      exitPrice: 210.5,
      exitDate: '2026-06-01',
    })

    expect(requestedUrl?.searchParams.get('exit_reason')).toBe('target_hit')
    expect(requestedUrl?.searchParams.get('exit_price')).toBe('210.5')
    expect(requestedUrl?.searchParams.get('exit_date')).toBe('2026-06-01')
  })

  it('deletePosition forwards a lone exit_price without exit_date rather than silently dropping it, leaving both-or-neither validation to the backend', async () => {
    let requestedUrl: URL | undefined
    server.use(
      http.delete('/api/portfolio/positions/:id', ({ request }) => {
        requestedUrl = new URL(request.url)
        return new HttpResponse(null, { status: 204 })
      }),
    )

    await deletePosition('pos_123', { exitPrice: 210.5 })

    expect(requestedUrl?.searchParams.get('exit_price')).toBe('210.5')
    expect(requestedUrl?.searchParams.has('exit_date')).toBe(false)
  })

  it('getClosedTrades with no arguments returns every closed trade, unfiltered', async () => {
    const response = await getClosedTrades()

    // The two fixed-date rows plus the mock store's own relative-date row
    // seeded specifically to fall inside the due-for-follow-up window.
    expect(response.items.map((item) => item.ticker).sort()).toEqual([
      'ADSK',
      'NVDA',
      'TSLA',
    ])
  })

  it('getClosedTrades({ dueForFollowUp: true }) narrows to the trade currently due for review', async () => {
    const response = await getClosedTrades({ dueForFollowUp: true })

    expect(response.items).toHaveLength(1)
    expect(response.items[0]?.ticker).toBe('NVDA')
    expect(response.items[0]?.follow_up_reviewed_at).toBeNull()
  })

  it('recordFollowUpReview sets follow_up_notes/follow_up_reviewed_at and drops the trade out of the due filter', async () => {
    const due = await getClosedTrades({ dueForFollowUp: true })
    const tradeId = due.items[0]?.id as string

    const updated = await recordFollowUpReview(tradeId, {
      follow_up_notes: 'Sold too early -- the tide was still bullish two months later.',
    })

    expect(updated.follow_up_notes).toBe(
      'Sold too early -- the tide was still bullish two months later.',
    )
    expect(updated.follow_up_reviewed_at).not.toBeNull()

    const stillDue = await getClosedTrades({ dueForFollowUp: true })
    expect(stillDue.items).toHaveLength(0)
  })

  it('recordFollowUpReview throws a 404 ApiError for a trade id that does not exist', async () => {
    await expect(
      recordFollowUpReview('does-not-exist', { follow_up_notes: 'Some hindsight.' }),
    ).rejects.toMatchObject({ status: 404 })
  })
})
