import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../../api/client'
import type { PositionOut } from '../../../api/portfolio'
import ClosePositionDialog from './ClosePositionDialog'

const aaplPosition: PositionOut = {
  id: 'pos_123',
  ticker: 'AAPL',
  quantity: 100,
  avg_cost_basis: 195.3,
  entry_date: '2026-05-14',
  current_price: 228.9,
  unrealized_pnl_pct: 17.2,
  signal: 'BUY',
  confidence: 72,
  confidence_band: 'High',
}

function renderDialog(overrides: Partial<ComponentProps<typeof ClosePositionDialog>> = {}) {
  const onConfirm = overrides.onConfirm ?? vi.fn()
  const onCancel = overrides.onCancel ?? vi.fn()
  const utils = render(
    <ClosePositionDialog
      position={aaplPosition}
      isPending={false}
      error={null}
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...overrides}
    />,
  )
  return { ...utils, onConfirm, onCancel }
}

describe('ClosePositionDialog', () => {
  it('renders nothing when position is null', () => {
    render(
      <ClosePositionDialog
        position={null}
        isPending={false}
          error={null}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows the ticker/quantity in the title and body when open', () => {
    renderDialog()

    expect(screen.getByText('Close Position: AAPL')).toBeInTheDocument()
    expect(
      screen.getByText('Close AAPL (100 shares)? This cannot be undone.'),
    ).toBeInTheDocument()
  })

  it('defaults the exit reason to Unspecified and does not show the override fields', () => {
    renderDialog()

    expect(screen.getByRole('combobox', { name: 'Exit reason' })).toHaveTextContent('Unspecified')
    expect(screen.queryByLabelText('Exit Price')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Exit Date')).not.toBeInTheDocument()
  })

  it('submits a default close with just the chosen exit_reason, no override', async () => {
    const user = userEvent.setup()
    const { onConfirm } = renderDialog()

    await user.click(screen.getByRole('combobox', { name: 'Exit reason' }))
    await user.click(screen.getByRole('option', { name: 'Target hit' }))
    await user.click(screen.getByRole('button', { name: 'Close Position' }))

    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onConfirm).toHaveBeenCalledWith({ exitReason: 'target_hit' })
  })

  it('calls onCancel when Cancel is clicked', async () => {
    const user = userEvent.setup()
    const { onCancel } = renderDialog()

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('reveals the manual exit price/date override fields once the checkbox is checked', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.click(
      screen.getByRole('checkbox', {
        name: "Backfill a historical exit price/date instead of today's live price",
      }),
    )

    expect(screen.getByLabelText('Exit Price')).toBeInTheDocument()
    expect(screen.getByLabelText('Exit Date')).toBeInTheDocument()
  })

  it('requires both exit price and exit date once the override checkbox is checked, without calling onConfirm', async () => {
    const user = userEvent.setup()
    const { onConfirm } = renderDialog()

    await user.click(
      screen.getByRole('checkbox', {
        name: "Backfill a historical exit price/date instead of today's live price",
      }),
    )
    await user.click(screen.getByRole('button', { name: 'Close Position' }))

    expect(screen.getByText('Exit price must be a positive number.')).toBeInTheDocument()
    expect(screen.getByText('Exit date is required.')).toBeInTheDocument()
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('rejects a non-positive exit price', async () => {
    const user = userEvent.setup()
    const { onConfirm } = renderDialog()

    await user.click(
      screen.getByRole('checkbox', {
        name: "Backfill a historical exit price/date instead of today's live price",
      }),
    )
    await user.type(screen.getByLabelText('Exit Price'), '0')
    await user.type(screen.getByLabelText('Exit Date'), '2026-06-01')
    await user.click(screen.getByRole('button', { name: 'Close Position' }))

    expect(screen.getByText('Exit price must be a positive number.')).toBeInTheDocument()
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('rejects an exit date before the position entry date, mirroring the backend validation', async () => {
    const user = userEvent.setup()
    const { onConfirm } = renderDialog()

    await user.click(
      screen.getByRole('checkbox', {
        name: "Backfill a historical exit price/date instead of today's live price",
      }),
    )
    await user.type(screen.getByLabelText('Exit Price'), '200')
    await user.type(screen.getByLabelText('Exit Date'), '2026-01-01')
    await user.click(screen.getByRole('button', { name: 'Close Position' }))

    expect(
      screen.getByText('Exit date must not be before the entry date (2026-05-14).'),
    ).toBeInTheDocument()
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('submits an override close with the manual exit price/date and chosen exit_reason', async () => {
    const user = userEvent.setup()
    const { onConfirm } = renderDialog()

    await user.click(screen.getByRole('combobox', { name: 'Exit reason' }))
    await user.click(screen.getByRole('option', { name: 'Stop hit' }))
    await user.click(
      screen.getByRole('checkbox', {
        name: "Backfill a historical exit price/date instead of today's live price",
      }),
    )
    await user.type(screen.getByLabelText('Exit Price'), '180.5')
    await user.type(screen.getByLabelText('Exit Date'), '2026-06-01')
    await user.click(screen.getByRole('button', { name: 'Close Position' }))

    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onConfirm).toHaveBeenCalledWith({
      exitReason: 'stop_hit',
      exitPrice: 180.5,
      exitDate: '2026-06-01',
    })
  })

  it('resets the form when switching to a different position', async () => {
    const user = userEvent.setup()
    const { rerender } = renderDialog()

    await user.click(
      screen.getByRole('checkbox', {
        name: "Backfill a historical exit price/date instead of today's live price",
      }),
    )
    await user.type(screen.getByLabelText('Exit Price'), '180.5')

    const zzzzPosition: PositionOut = { ...aaplPosition, id: 'pos_456', ticker: 'ZZZZ' }
    rerender(
      <ClosePositionDialog
        position={zzzzPosition}
        isPending={false}
          error={null}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByText('Close Position: ZZZZ')).toBeInTheDocument()
    expect(screen.queryByLabelText('Exit Price')).not.toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Exit reason' })).toHaveTextContent('Unspecified')
  })

  it('shows an ApiError via common/ErrorState when error is set', () => {
    renderDialog({ error: new ApiError(404, 'Position not found') })

    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('Position not found')).toBeInTheDocument()
  })

  it('disables Cancel and the submit button while isPending is true', () => {
    renderDialog({ isPending: true })

    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Close Position' })).toBeDisabled()
  })
})
