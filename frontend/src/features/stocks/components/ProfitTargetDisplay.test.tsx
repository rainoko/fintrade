import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { ProfitTargetOut } from '../../../api/stocks'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import ProfitTargetDisplay from './ProfitTargetDisplay'

const target: ProfitTargetOut = {
  price: 245.0,
  source: 'channel',
  distance_to_stop: 9.3,
  distance_to_target: 18.6,
  reward_risk_ratio: 2.0,
  meets_minimum_reward_risk: true,
}

describe('ProfitTargetDisplay', () => {
  it('renders the target price and a reward:risk badge for a fresh BUY', () => {
    renderWithTheme(<ProfitTargetDisplay profitTarget={target} signal="BUY" />)

    expect(screen.getByText('Target $245.00')).toBeInTheDocument()
    expect(screen.getByText('2.0:1')).toBeInTheDocument()
  })

  it('renders an explained em dash for a non-BUY signal', async () => {
    const user = userEvent.setup()
    renderWithTheme(<ProfitTargetDisplay profitTarget={null} signal="HOLD" />)

    expect(screen.getByText('Profit Target: —')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Profit Target help' }))
    expect(
      screen.getByText(/this ticker is currently HOLD/),
    ).toBeInTheDocument()
  })

  it('renders an explained em dash for a BUY with no current candidate', () => {
    renderWithTheme(<ProfitTargetDisplay profitTarget={null} signal="BUY" />)

    expect(screen.getByText('Profit Target: —')).toBeInTheDocument()
  })

  it('renders "n/a" for the ratio when the API omits reward_risk_ratio entirely', () => {
    const targetWithoutRatio: ProfitTargetOut = {
      price: target.price,
      source: target.source,
      distance_to_stop: target.distance_to_stop,
      distance_to_target: target.distance_to_target,
      meets_minimum_reward_risk: target.meets_minimum_reward_risk,
      // reward_risk_ratio intentionally omitted -- an optional field the
      // backend can leave unset, distinct from an explicit `null`.
    }
    renderWithTheme(<ProfitTargetDisplay profitTarget={targetWithoutRatio} signal="BUY" />)

    expect(screen.getByText('Target $245.00')).toBeInTheDocument()
    expect(screen.getByText('n/a')).toBeInTheDocument()
  })
})
