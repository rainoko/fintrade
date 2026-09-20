import { describe, expect, it } from 'vitest'
import type { InsiderClusterOut } from '../api/stocks'
import { sortClustersByRecentWindowEnd } from './insiderClusters'

function buildCluster(overrides: Partial<InsiderClusterOut> = {}): InsiderClusterOut {
  return {
    direction: 'buy',
    insiders: ['Alice Smith', 'Bob Jones', 'Carol White'],
    window_start_date: '2026-07-15',
    window_end_date: '2026-08-01',
    transaction_count: 3,
    total_shares: 150_000,
    total_value: 33_000_000,
    ...overrides,
  }
}

describe('sortClustersByRecentWindowEnd', () => {
  it('orders clusters most-recent window_end_date first', () => {
    const june = buildCluster({ window_start_date: '2026-06-01', window_end_date: '2026-06-15' })
    const april = buildCluster({ window_start_date: '2026-04-01', window_end_date: '2026-04-15' })
    const august = buildCluster({ window_start_date: '2026-08-01', window_end_date: '2026-08-20' })

    expect(sortClustersByRecentWindowEnd([june, april, august])).toEqual([
      august,
      june,
      april,
    ])
  })

  it('returns a new array rather than mutating the input', () => {
    const clusters = [
      buildCluster({ window_end_date: '2026-06-15' }),
      buildCluster({ window_end_date: '2026-08-20' }),
    ]
    const original = [...clusters]

    const sorted = sortClustersByRecentWindowEnd(clusters)

    expect(sorted).not.toBe(clusters)
    expect(clusters).toEqual(original)
  })

  it('returns an empty array unchanged', () => {
    expect(sortClustersByRecentWindowEnd([])).toEqual([])
  })
})
