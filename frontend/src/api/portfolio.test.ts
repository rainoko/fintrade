import { beforeEach, describe, expect, it } from 'vitest'
import { resetPortfolioStore } from '../../tests/mocks/handlers'
import { addPosition, deletePosition, getPortfolio, getPortfolioRisk } from './portfolio'

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

  it('deletePosition removes an existing position', async () => {
    await expect(deletePosition('pos_123')).resolves.toBeUndefined()

    const portfolio = await getPortfolio()
    expect(portfolio.positions).toHaveLength(0)
  })

  it('deletePosition throws a 404 ApiError for an id that does not exist', async () => {
    await expect(deletePosition('does-not-exist')).rejects.toMatchObject({ status: 404 })
  })
})
