import { beforeEach, describe, expect, it } from 'vitest'
import { resetDailyHomeworkStore } from '../../tests/mocks/handlers'
import {
  getDailyHomeworkToday,
  getYesterdayTradingSuggestion,
  recordDailyHomework,
} from './homework'

describe('api/homework', () => {
  beforeEach(() => {
    resetDailyHomeworkStore()
  })

  it('getDailyHomeworkToday returns a null entry before anything is recorded today', async () => {
    const response = await getDailyHomeworkToday()
    expect(response.entry).toBeNull()
  })

  it('recordDailyHomework computes total_score and band, and persists the entry', async () => {
    const created = await recordDailyHomework({
      physical_state_score: 2,
      yesterday_trading_score: 2,
      trade_planning_score: 2,
      mood_score: 1,
      schedule_score: 1,
    })

    expect(created.total_score).toBe(8)
    expect(created.band).toBe('green')

    const today = await getDailyHomeworkToday()
    expect(today.entry?.total_score).toBe(8)
    expect(today.entry?.band).toBe('green')
  })

  it('a second submission for the same day overwrites the first rather than duplicating', async () => {
    await recordDailyHomework({
      physical_state_score: 0,
      yesterday_trading_score: 0,
      trade_planning_score: 0,
      mood_score: 0,
      schedule_score: 0,
    })
    const second = await recordDailyHomework({
      physical_state_score: 2,
      yesterday_trading_score: 2,
      trade_planning_score: 2,
      mood_score: 2,
      schedule_score: 2,
    })

    expect(second.total_score).toBe(10)
    const today = await getDailyHomeworkToday()
    expect(today.entry?.total_score).toBe(10)
  })

  it('getYesterdayTradingSuggestion returns a suggested score derived from yesterday\'s trading', async () => {
    const suggestion = await getYesterdayTradingSuggestion()
    expect(suggestion.suggested_score).toBe(2)
    expect(suggestion.net_realized_pnl).toBe(150.0)
  })
})
