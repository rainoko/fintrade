import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { ExtendedDataOut, InsiderTransactionOut } from '../../../api/stocks'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import FundamentalDataPanel from './FundamentalDataPanel'

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

describe('FundamentalDataPanel', () => {
  it('renders nothing when extended_data is missing from the response', () => {
    const { container } = renderWithTheme(<FundamentalDataPanel extendedData={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when extended_data is null', () => {
    const { container } = renderWithTheme(<FundamentalDataPanel extendedData={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows a distinct unavailable state when the fallback provider is active, not a blank panel', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <FundamentalDataPanel
        extendedData={buildExtendedData({
          earnings_date: null,
          ex_dividend_date: null,
          shares_short: null,
          short_ratio: null,
          short_percent_of_float: null,
          float_shares: null,
          unavailable_reason: 'fallback_provider_active',
        })}
      />,
    )

    expect(screen.getByText('Unavailable -- fallback provider active')).toBeInTheDocument()
    expect(
      screen.getByText(/the fallback \(Stooq\) market data provider is currently serving/),
    ).toBeInTheDocument()
    // No stat cards / earnings warning / insider table should render in this state.
    expect(screen.queryByText('Earnings Date')).not.toBeInTheDocument()
    expect(screen.queryByRole('table', { name: 'Insider transactions' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Fundamental Data help' }))
    expect(
      screen.getByText(/Not the same as "checked, nothing found"/),
    ).toBeInTheDocument()
  })

  it('shows a prominent warning banner when earnings fall within the 14-day window', () => {
    renderWithTheme(
      <FundamentalDataPanel
        extendedData={buildExtendedData({
          earnings_date: '2026-09-25',
          earnings_within_warning_days: true,
        })}
      />,
    )

    const banner = screen.getByTestId('earnings-warning-banner')
    expect(banner).toHaveTextContent('Earnings expected 2026-09-25 -- within the next 14 days.')
  })

  it('does not show the warning banner when earnings are outside the window', () => {
    renderWithTheme(
      <FundamentalDataPanel
        extendedData={buildExtendedData({
          earnings_date: '2026-12-01',
          earnings_within_warning_days: false,
        })}
      />,
    )

    expect(screen.queryByTestId('earnings-warning-banner')).not.toBeInTheDocument()
  })

  it('shows "None scheduled" for null earnings/ex-dividend dates', () => {
    renderWithTheme(
      <FundamentalDataPanel
        extendedData={buildExtendedData({ earnings_date: null, ex_dividend_date: null })}
      />,
    )

    const noneScheduled = screen.getAllByText('None scheduled')
    expect(noneScheduled).toHaveLength(2)
  })

  it('explains the current earnings date value via MetricHelp, flagging the 14-day window', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <FundamentalDataPanel
        extendedData={buildExtendedData({
          earnings_date: '2026-09-25',
          earnings_within_warning_days: true,
        })}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Earnings Date help' }))
    expect(
      screen.getByText(/within the next 14 days\. Elder's own advice/),
    ).toBeInTheDocument()
  })

  it('renders short-interest figures and flags an elevated short-percent-of-float as squeeze fuel', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <FundamentalDataPanel
        extendedData={buildExtendedData({
          shares_short: 5_000_000,
          short_ratio: 4.2,
          short_percent_of_float: 0.15,
          float_shares: 33_000_000,
        })}
      />,
    )

    expect(screen.getByText('5,000,000')).toBeInTheDocument()
    expect(screen.getByText('4.2')).toBeInTheDocument()
    expect(screen.getByText('15.0%')).toBeInTheDocument()
    expect(screen.getByText('33,000,000')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Short Interest help' }))
    expect(screen.getByText(/elevated short-percent-of-float/)).toBeInTheDocument()
    expect(screen.getByText(/meaningful squeeze fuel/)).toBeInTheDocument()
  })

  it('shows "—" placeholders and an unreported explanation when no short-interest data exists', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <FundamentalDataPanel
        extendedData={buildExtendedData({
          shares_short: null,
          short_ratio: null,
          short_percent_of_float: null,
          float_shares: null,
        })}
      />,
    )

    expect(screen.getAllByText('—').length).toBeGreaterThan(0)

    await user.click(screen.getByRole('button', { name: 'Short Interest help' }))
    expect(
      screen.getByText('Currently unavailable for this ticker -- not reported by this data source.'),
    ).toBeInTheDocument()
  })

  it('shows an empty-state message when there are no insider transactions', () => {
    renderWithTheme(<FundamentalDataPanel extendedData={buildExtendedData()} />)

    expect(
      screen.getByText('No insider transactions currently reported for this ticker.'),
    ).toBeInTheDocument()
  })

  it('renders insider transactions in a table and notes the 3-filing cluster threshold', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <FundamentalDataPanel
        extendedData={buildExtendedData({
          insider_transactions: [
            insiderTransaction,
            { ...insiderTransaction, insider: 'Someone Else', start_date: '2026-08-05' },
            { ...insiderTransaction, insider: null, position: null, start_date: null },
          ],
        })}
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
      <FundamentalDataPanel
        extendedData={buildExtendedData({ insider_transactions: [insiderTransaction] })}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Insider Transactions help' }))
    expect(screen.getByText(/1 filing shown/)).toBeInTheDocument()
    expect(
      screen.getByText(/on its own, not usually treated as a meaningful signal/),
    ).toBeInTheDocument()
  })
})
