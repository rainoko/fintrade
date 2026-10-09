import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { ExtendedDataOut } from '../../../api/stocks'
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

describe('FundamentalDataPanel', () => {
  // `extendedData: ExtendedDataOut | null | undefined` and its
  // `if (!extendedData) return null` guard (and the two tests that used to
  // exercise it here) were removed in frontend-fundamental-data-panel-
  // followups: `AnalysisResponse.extended_data` is a genuinely non-optional,
  // non-nullable field per backend/app/api/schemas.py, so `extendedData` is
  // now typed as plain `ExtendedDataOut` and this defensive case can no
  // longer occur (or even type-check).
  //
  // Insider Transactions cases (the unavailable-state table/callout
  // assertions, the insider-transactions table itself, the cluster
  // callouts) moved to `InsiderTransactionsPanel.test.tsx` in
  // frontend-stock-detail-insider-transactions-last, alongside the
  // extraction of that card into its own component.

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

    expect(
      screen.getByText('Unavailable -- fallback provider active'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        /the fallback \(Stooq\) market data provider is currently serving/,
      ),
    ).toBeInTheDocument()
    // No stat cards should render in this state.
    expect(screen.queryByText('Earnings Date')).not.toBeInTheDocument()

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
    expect(banner).toHaveTextContent(
      'Earnings expected 2026-09-25 -- within the next 14 days.',
    )
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
      screen.getByText(
        'Currently unavailable for this ticker -- not reported by this data source.',
      ),
    ).toBeInTheDocument()
  })
})
