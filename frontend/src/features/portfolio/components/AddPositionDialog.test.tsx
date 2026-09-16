import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '../../../../tests/renderWithProviders'
import AddPositionDialog from './AddPositionDialog'

async function fillValidForm(user: ReturnType<typeof userEvent.setup>, ticker: string) {
  await user.type(screen.getByLabelText('Ticker'), ticker)
  await user.type(screen.getByLabelText('Quantity'), '10')
  await user.type(screen.getByLabelText('Avg Cost Basis'), '100')
  await user.type(screen.getByLabelText('Entry Date'), '2026-01-15')
}

describe('AddPositionDialog', () => {
  it('renders nothing when closed', () => {
    renderWithProviders(
      <AddPositionDialog open={false} onClose={vi.fn()} existingTickers={[]} />,
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows validation errors and does not submit when fields are missing/invalid', async () => {
    const user = userEvent.setup()
    renderWithProviders(<AddPositionDialog open onClose={vi.fn()} existingTickers={[]} />)

    await user.type(screen.getByLabelText('Quantity'), '0')
    await user.type(screen.getByLabelText('Avg Cost Basis'), '-5')
    await user.click(screen.getByRole('button', { name: 'Add Position' }))

    expect(screen.getByText('Ticker is required.')).toBeInTheDocument()
    expect(screen.getByText('Quantity must be a positive number.')).toBeInTheDocument()
    expect(
      screen.getByText('Average cost basis must be a positive number.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Entry date is required.')).toBeInTheDocument()
    // Still in the form (no success message), confirming nothing was submitted.
    expect(screen.getByLabelText('Ticker')).toBeInTheDocument()
  })

  it('adds a new position and shows the "added" success message', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <AddPositionDialog open onClose={vi.fn()} existingTickers={['AAPL']} />,
    )

    await fillValidForm(user, 'MSFT')
    await user.click(screen.getByRole('button', { name: 'Add Position' }))

    await waitFor(() =>
      expect(screen.getByText('Added MSFT to your portfolio.')).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: 'Done' })).toBeInTheDocument()
  })

  it('shows the merge message when the ticker is already held', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <AddPositionDialog open onClose={vi.fn()} existingTickers={['AAPL']} />,
    )

    await fillValidForm(user, 'aapl')
    await user.click(screen.getByRole('button', { name: 'Add Position' }))

    await waitFor(() =>
      expect(
        screen.getByText(/merged into your existing aapl position/i),
      ).toBeInTheDocument(),
    )
  })

  it('closes via Done after a successful submit', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    renderWithProviders(<AddPositionDialog open onClose={onClose} existingTickers={[]} />)

    await fillValidForm(user, 'MSFT')
    await user.click(screen.getByRole('button', { name: 'Add Position' }))
    await waitFor(() => screen.getByRole('button', { name: 'Done' }))
    await user.click(screen.getByRole('button', { name: 'Done' }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('surfaces a 422 ApiError via common/ErrorState when the server rejects the submit', async () => {
    const user = userEvent.setup()
    renderWithProviders(<AddPositionDialog open onClose={vi.fn()} existingTickers={[]} />)

    await fillValidForm(user, 'OVERFLOW')
    await user.click(screen.getByRole('button', { name: 'Add Position' }))

    await waitFor(() =>
      expect(
        screen.getByText(
          'Merging this position would produce a value too large to represent.',
        ),
      ).toBeInTheDocument(),
    )
    // Still in form mode, not the success view — the user can correct and retry.
    expect(screen.getByLabelText('Ticker')).toBeInTheDocument()
  })

  it('resets the form and any prior success/error state each time it reopens', async () => {
    const user = userEvent.setup()
    const { rerender } = renderWithProviders(
      <AddPositionDialog open onClose={vi.fn()} existingTickers={[]} />,
    )

    await fillValidForm(user, 'MSFT')
    await user.click(screen.getByRole('button', { name: 'Add Position' }))
    await waitFor(() => screen.getByRole('button', { name: 'Done' }))

    rerender(<AddPositionDialog open={false} onClose={vi.fn()} existingTickers={[]} />)
    rerender(<AddPositionDialog open onClose={vi.fn()} existingTickers={[]} />)

    expect(screen.queryByText('Added MSFT to your portfolio.')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Ticker')).toHaveValue('')
  })
})
