import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import PositionProfitTargetCell from './PositionProfitTargetCell'

describe('PositionProfitTargetCell', () => {
  it('shows an explained em dash when profitTarget is null', () => {
    renderWithProviders(<PositionProfitTargetCell profitTarget={null} />)

    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('shows the target price and a passing reward:risk badge', () => {
    renderWithProviders(
      <PositionProfitTargetCell
        profitTarget={{
          price: 245.0,
          source: 'channel',
          distance_to_stop: 9.3,
          distance_to_target: 18.6,
          reward_risk_ratio: 2.0,
          meets_minimum_reward_risk: true,
        }}
      />,
    )

    expect(screen.getByText('$245.00')).toBeInTheDocument()
    expect(screen.getByText('2.0:1')).toBeInTheDocument()
    expect(screen.queryByLabelText('Below the 2:1 minimum')).not.toBeInTheDocument()
  })

  it('visually flags a reward:risk ratio that fails the 2:1 rule', () => {
    renderWithProviders(
      <PositionProfitTargetCell
        profitTarget={{
          price: 235.0,
          source: 'support_resistance',
          distance_to_stop: 9.3,
          distance_to_target: 8.6,
          reward_risk_ratio: 0.9,
          meets_minimum_reward_risk: false,
        }}
      />,
    )

    expect(screen.getByText('$235.00')).toBeInTheDocument()
    expect(screen.getByText('0.9:1')).toBeInTheDocument()
    expect(screen.getByLabelText('Below the 2:1 minimum')).toBeInTheDocument()
  })

  it('renders "n/a" for the ratio when the API omits reward_risk_ratio entirely', () => {
    renderWithProviders(
      <PositionProfitTargetCell
        profitTarget={{
          price: 100.0,
          source: 'channel',
          distance_to_stop: 5.0,
          distance_to_target: 4.0,
          meets_minimum_reward_risk: false,
          // reward_risk_ratio intentionally omitted -- an optional field the
          // backend can leave unset, distinct from an explicit `null`.
        }}
      />,
    )

    expect(screen.getByText('$100.00')).toBeInTheDocument()
    expect(screen.getByText('n/a')).toBeInTheDocument()
  })

  it('opens MetricHelp with the current target/ratio interpretation', async () => {
    const user = userEvent.setup()

    renderWithProviders(
      <PositionProfitTargetCell
        profitTarget={{
          price: 245.0,
          source: 'channel',
          distance_to_stop: 9.3,
          distance_to_target: 18.6,
          reward_risk_ratio: 2.0,
          meets_minimum_reward_risk: true,
        }}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Profit Target help' }))
    expect(
      screen.getByText(/Currently 245.00, from the channel\/Tradebill formula/),
    ).toBeInTheDocument()
  })

  it('opens MetricHelp explaining the no-candidate null case', async () => {
    const user = userEvent.setup()

    renderWithProviders(<PositionProfitTargetCell profitTarget={null} />)

    await user.click(screen.getByRole('button', { name: 'Profit Target help' }))
    expect(
      screen.getByText(/neither technique.*currently produces a candidate/),
    ).toBeInTheDocument()
  })
})
