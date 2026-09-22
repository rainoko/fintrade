import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ClosedTradeOut } from '../../../api/portfolio'
import { resetPortfolioStore } from '../../../../tests/mocks/handlers'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import FollowUpReviewDialog from './FollowUpReviewDialog'

const adskTrade: ClosedTradeOut = {
  id: 'trade_abc123',
  ticker: 'ADSK',
  quantity: 100,
  entry_price: 51.77,
  entry_date: '2026-03-02',
  exit_price: 53.78,
  exit_date: '2026-03-09',
  realized_pnl: 201.0,
  exit_reason: 'target_hit',
}

describe('FollowUpReviewDialog', () => {
  beforeEach(() => {
    resetPortfolioStore()
  })

  it('renders nothing when trade is null', () => {
    renderWithProviders(<FollowUpReviewDialog trade={null} onClose={vi.fn()} />)

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('calls onClose when Cancel is clicked', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    renderWithProviders(<FollowUpReviewDialog trade={adskTrade} onClose={onClose} />)

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('shows the trade’s ticker in the title', () => {
    renderWithProviders(<FollowUpReviewDialog trade={adskTrade} onClose={vi.fn()} />)

    expect(screen.getByText('Follow-Up Review: ADSK')).toBeInTheDocument()
  })

  it('shows a validation error and does not submit for blank notes', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    renderWithProviders(<FollowUpReviewDialog trade={adskTrade} onClose={onClose} />)

    await user.click(screen.getByRole('button', { name: 'Save Review' }))

    expect(screen.getByText('Follow-up notes are required.')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('treats whitespace-only notes as blank', async () => {
    const user = userEvent.setup()
    renderWithProviders(<FollowUpReviewDialog trade={adskTrade} onClose={vi.fn()} />)

    await user.type(screen.getByLabelText('Follow-up notes'), '   ')
    await user.click(screen.getByRole('button', { name: 'Save Review' }))

    expect(screen.getByText('Follow-up notes are required.')).toBeInTheDocument()
  })

  it('records a review and closes the dialog on success', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    renderWithProviders(<FollowUpReviewDialog trade={adskTrade} onClose={onClose} />)

    await user.type(
      screen.getByLabelText('Follow-up notes'),
      'Sold too early -- the tide was still bullish two months later.',
    )
    await user.click(screen.getByRole('button', { name: 'Save Review' }))

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
  })

  it('shows an ApiError via common/ErrorState when the trade cannot be found', async () => {
    const user = userEvent.setup()
    const unknownTrade: ClosedTradeOut = { ...adskTrade, id: 'does-not-exist' }
    renderWithProviders(<FollowUpReviewDialog trade={unknownTrade} onClose={vi.fn()} />)

    await user.type(screen.getByLabelText('Follow-up notes'), 'Some hindsight.')
    await user.click(screen.getByRole('button', { name: 'Save Review' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })

  it('resets notes/errors when switching to review a different trade', async () => {
    const user = userEvent.setup()
    const { rerender } = renderWithProviders(
      <FollowUpReviewDialog trade={adskTrade} onClose={vi.fn()} />,
    )

    await user.type(screen.getByLabelText('Follow-up notes'), 'Some draft notes.')

    const tslaTrade: ClosedTradeOut = { ...adskTrade, id: 'trade_def456', ticker: 'TSLA' }
    rerender(<FollowUpReviewDialog trade={tslaTrade} onClose={vi.fn()} />)

    expect(screen.getByText('Follow-Up Review: TSLA')).toBeInTheDocument()
    expect(screen.getByLabelText('Follow-up notes')).toHaveValue('')
  })

  it('closes when the trade prop transitions to null', async () => {
    const { rerender } = renderWithProviders(
      <FollowUpReviewDialog trade={adskTrade} onClose={vi.fn()} />,
    )
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    rerender(<FollowUpReviewDialog trade={null} onClose={vi.fn()} />)

    // MUI's Dialog stays mounted through its own closing transition, so this
    // must poll rather than assert synchronously right after the rerender.
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})
