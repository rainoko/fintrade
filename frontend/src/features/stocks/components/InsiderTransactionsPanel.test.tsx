import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type {
  ExtendedDataOut,
  InsiderClusterOut,
  InsiderTransactionOut,
} from '../../../api/stocks'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import InsiderTransactionsPanel from './InsiderTransactionsPanel'

function buildExtendedData(overrides: Partial<ExtendedDataOut> = {}): ExtendedDataOut {
  return {
    earnings_date: '2026-10-29',
    earnings_within_warning_days: false,
    ex_dividend_date: '2026-11-15',
    shares_short: 12_345_678,
    short_ratio: 2.3,
    short_percent_of_float: 0.045,
    float_shares: 1_000_000_000,
    insider_transactions: [],
    unavailable_reason: null,
    ...overrides,
  }
}

const insiderTransaction: InsiderTransactionOut = {
  insider: 'Cook Timothy D',
  position: 'Chief Executive Officer',
  transaction_text: 'Sale at price 220.00 - 225.00 per share.',
  shares: 50_000,
  value: 11_000_000,
  start_date: '2026-08-01',
  ownership: 'D',
}

function buildInsiderCluster(
  overrides: Partial<InsiderClusterOut> = {},
): InsiderClusterOut {
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

describe('InsiderTransactionsPanel', () => {
  it('shows its own distinct unavailable state when the fallback provider is active, not a blank panel', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <InsiderTransactionsPanel
        extendedData={buildExtendedData({
          insider_transactions: [],
          unavailable_reason: 'fallback_provider_active',
        })}
        insiderClusters={[]}
      />,
    )

    expect(
      screen.getByText('Unavailable -- fallback provider active'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        /the fallback \(Stooq\) market data provider is currently serving/,
      ),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('table', { name: 'Insider transactions' }),
    ).not.toBeInTheDocument()
    expect(screen.queryByTestId('insider-cluster-callout')).not.toBeInTheDocument()
    expect(screen.queryByTestId('insider-cluster-empty-note')).not.toBeInTheDocument()

    await user.click(
      screen.getByRole('button', { name: 'Insider Transactions help' }),
    )
    expect(
      screen.getByText(/Not the same as "checked, nothing found"/),
    ).toBeInTheDocument()
  })

  it('shows an empty-state message when there are no insider transactions, with no cluster note either', () => {
    renderWithTheme(
      <InsiderTransactionsPanel
        extendedData={buildExtendedData()}
        insiderClusters={[]}
      />,
    )

    expect(
      screen.getByText('No insider transactions currently reported for this ticker.'),
    ).toBeInTheDocument()
    // Nothing to say about clusters when there are no raw filings at all --
    // the table's own empty message already covers it, and a second empty
    // note underneath would be redundant noise (this component's own doc
    // comment / this task's `decisions` entry).
    expect(screen.queryByTestId('insider-cluster-empty-note')).not.toBeInTheDocument()
    expect(screen.queryByTestId('insider-cluster-callout')).not.toBeInTheDocument()
  })

  it('renders insider transactions in a table and notes the 3-filing cluster threshold', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <InsiderTransactionsPanel
        extendedData={buildExtendedData({
          insider_transactions: [
            insiderTransaction,
            { ...insiderTransaction, insider: 'Someone Else', start_date: '2026-08-05' },
            { ...insiderTransaction, insider: null, position: null, start_date: null },
          ],
        })}
        insiderClusters={[]}
      />,
    )

    expect(
      screen.getByRole('table', { name: 'Insider transactions' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Cook Timothy D')).toBeInTheDocument()
    expect(screen.getByText('Someone Else')).toBeInTheDocument()
    expect(screen.getAllByText('Chief Executive Officer')).toHaveLength(2)
    expect(screen.getAllByText('$11,000,000.00')).toHaveLength(3)
    // Third row's `position` is null -- rendered as an explicit '—', not a blank cell.
    const table = screen.getByRole('table', { name: 'Insider transactions' })
    expect(table).toHaveTextContent('—')

    await user.click(screen.getByRole('button', { name: 'Insider Transactions help' }))
    expect(screen.getByText(/3 filings shown/)).toBeInTheDocument()
    expect(screen.getByText(/Three or more filings are shown/)).toBeInTheDocument()
  })

  it('notes a single insider filing falls short of the cluster threshold', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <InsiderTransactionsPanel
        extendedData={buildExtendedData({ insider_transactions: [insiderTransaction] })}
        insiderClusters={[]}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Insider Transactions help' }))
    expect(screen.getByText(/1 filing shown/)).toBeInTheDocument()
    expect(
      screen.getByText(/on its own, not usually treated as a meaningful signal/),
    ).toBeInTheDocument()
  })

  it('shows a quiet "no cluster detected" note when there are filings but no qualifying cluster', () => {
    renderWithTheme(
      <InsiderTransactionsPanel
        extendedData={buildExtendedData({ insider_transactions: [insiderTransaction] })}
        insiderClusters={[]}
      />,
    )

    expect(screen.getByTestId('insider-cluster-empty-note')).toHaveTextContent(
      'No insider-transaction cluster currently detected',
    )
    expect(screen.queryByTestId('insider-cluster-callout')).not.toBeInTheDocument()
  })

  it('renders a buy-cluster callout, distinct from the underlying signal palette', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <InsiderTransactionsPanel
        extendedData={buildExtendedData({
          insider_transactions: [insiderTransaction],
        })}
        insiderClusters={[
          buildInsiderCluster({
            direction: 'buy',
            insiders: ['Alice Smith', 'Bob Jones', 'Carol White'],
            window_start_date: '2026-07-01',
            window_end_date: '2026-07-20',
            transaction_count: 3,
            total_shares: 90_000,
            total_value: 4_500_000,
          }),
        ]}
      />,
    )

    expect(screen.getByText('BUY CLUSTER')).toBeInTheDocument()
    expect(screen.getByTestId('insider-cluster-callout')).toHaveTextContent(
      '3 distinct insiders (Alice Smith, Bob Jones, Carol White) -- 3 filings between Jul 1, 2026 and Jul 20, 2026, 90,000 shares, $4,500,000.00.',
    )
    expect(screen.queryByTestId('insider-cluster-empty-note')).not.toBeInTheDocument()

    await user.click(
      screen.getByRole('button', { name: 'Insider-Transaction Clusters help' }),
    )
    expect(screen.getByText(/1 cluster currently detected/)).toBeInTheDocument()
    expect(screen.getByText(/Buy cluster: 3 distinct insiders/)).toBeInTheDocument()
  })

  it('renders a sell-cluster callout with null totals rendered without a trailing shares/value clause', () => {
    renderWithTheme(
      <InsiderTransactionsPanel
        extendedData={buildExtendedData({ insider_transactions: [insiderTransaction] })}
        insiderClusters={[
          buildInsiderCluster({
            direction: 'sell',
            insiders: ['Dana Lee', 'Evan Park', 'Fay Chen', 'Gus Ortiz'],
            window_start_date: '2026-06-01',
            window_end_date: '2026-06-25',
            transaction_count: 5,
            total_shares: null,
            total_value: null,
          }),
        ]}
      />,
    )

    expect(screen.getByText('SELL CLUSTER')).toBeInTheDocument()
    expect(screen.getByTestId('insider-cluster-callout')).toHaveTextContent(
      '4 distinct insiders (Dana Lee, Evan Park, Fay Chen, Gus Ortiz) -- 5 filings between Jun 1, 2026 and Jun 25, 2026.',
    )
  })

  it('shows multiple clusters, most recent window first', () => {
    renderWithTheme(
      <InsiderTransactionsPanel
        extendedData={buildExtendedData({ insider_transactions: [insiderTransaction] })}
        insiderClusters={[
          // Deliberately unsorted input (mid, earliest, latest) so the
          // sort-by-window_end_date comparator is exercised in both
          // directions (a later-than-b and a earlier-than-b), not just one.
          buildInsiderCluster({
            direction: 'sell',
            window_start_date: '2026-06-01',
            window_end_date: '2026-06-15',
          }),
          buildInsiderCluster({
            direction: 'buy',
            window_start_date: '2026-04-01',
            window_end_date: '2026-04-15',
          }),
          buildInsiderCluster({
            direction: 'sell',
            window_start_date: '2026-08-01',
            window_end_date: '2026-08-20',
          }),
        ]}
      />,
    )

    const callouts = screen.getAllByTestId('insider-cluster-callout')
    expect(callouts).toHaveLength(3)
    // Aug (latest window_end_date) first, then Jun, then Apr (earliest) last.
    expect(callouts[0]).toHaveTextContent('Aug 1, 2026')
    expect(callouts[1]).toHaveTextContent('Jun 1, 2026')
    expect(callouts[2]).toHaveTextContent('Apr 1, 2026')
  })

  it('treats a missing insiderClusters value (stale test fixture) the same as an empty array', () => {
    renderWithTheme(
      <InsiderTransactionsPanel
        extendedData={buildExtendedData({ insider_transactions: [insiderTransaction] })}
        insiderClusters={undefined}
      />,
    )

    expect(screen.getByTestId('insider-cluster-empty-note')).toBeInTheDocument()
  })
})
