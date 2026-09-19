import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { renderWithTheme } from '../../../../tests/renderWithTheme'
import InfoBalloon, { AnchoredInfoBalloon } from './InfoBalloon'

describe('InfoBalloon', () => {
  it('renders only the trigger, not the balloon content, before it is clicked', () => {
    renderWithTheme(
      <InfoBalloon
        triggerAriaLabel="Why BUY?"
        title="Why BUY?"
        content="Explanation body."
      >
        <span>BUY</span>
      </InfoBalloon>,
    )

    expect(screen.getByText('BUY')).toBeInTheDocument()
    expect(screen.queryByText('Explanation body.')).not.toBeInTheDocument()
  })

  it('opens the balloon with the title and content on click, and closes on a second interaction', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <InfoBalloon
        triggerAriaLabel="Why BUY?"
        title="Why BUY?"
        content="Explanation body."
      >
        <span>BUY</span>
      </InfoBalloon>,
    )

    await user.click(screen.getByRole('button', { name: 'Why BUY?' }))

    expect(screen.getByText('Explanation body.')).toBeInTheDocument()
    expect(screen.getAllByText('Why BUY?').length).toBeGreaterThanOrEqual(1)

    await user.keyboard('{Escape}')

    expect(screen.queryByText('Explanation body.')).not.toBeInTheDocument()
  })

  it('accepts rich ReactNode content, not just a plain string', async () => {
    const user = userEvent.setup()
    renderWithTheme(
      <InfoBalloon
        triggerAriaLabel="Why HOLD?"
        title="Why HOLD?"
        content={
          <ul>
            <li>Tide: Bullish</li>
            <li>Wave: not met</li>
          </ul>
        }
      >
        <span>HOLD</span>
      </InfoBalloon>,
    )

    await user.click(screen.getByRole('button', { name: 'Why HOLD?' }))

    expect(screen.getByText('Tide: Bullish')).toBeInTheDocument()
    expect(screen.getByText('Wave: not met')).toBeInTheDocument()
  })
})

describe('AnchoredInfoBalloon', () => {
  it('renders nothing (closed) when anchorPosition is null, even if open is true', () => {
    renderWithTheme(
      <AnchoredInfoBalloon
        open={true}
        anchorPosition={null}
        onClose={vi.fn()}
        title="Divergence"
        content="Explanation body."
        ariaLabel="Divergence details"
      />,
    )

    expect(screen.queryByText('Explanation body.')).not.toBeInTheDocument()
  })

  it('renders nothing (closed) when open is false, even with an anchorPosition', () => {
    renderWithTheme(
      <AnchoredInfoBalloon
        open={false}
        anchorPosition={{ top: 10, left: 20 }}
        onClose={vi.fn()}
        title="Divergence"
        content="Explanation body."
        ariaLabel="Divergence details"
      />,
    )

    expect(screen.queryByText('Explanation body.')).not.toBeInTheDocument()
  })

  it('renders the title/content at the given anchorPosition when open with a real anchorPosition', () => {
    renderWithTheme(
      <AnchoredInfoBalloon
        open={true}
        anchorPosition={{ top: 10, left: 20 }}
        onClose={vi.fn()}
        title="Divergence"
        content="Explanation body."
        ariaLabel="Divergence details"
      />,
    )

    expect(screen.getByText('Divergence')).toBeInTheDocument()
    expect(screen.getByText('Explanation body.')).toBeInTheDocument()
    expect(screen.getByLabelText('Divergence details')).toBeInTheDocument()
  })

  it('calls onClose when dismissed (e.g. Escape)', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    renderWithTheme(
      <AnchoredInfoBalloon
        open={true}
        anchorPosition={{ top: 10, left: 20 }}
        onClose={onClose}
        title="Divergence"
        content="Explanation body."
        ariaLabel="Divergence details"
      />,
    )

    await user.keyboard('{Escape}')

    expect(onClose).toHaveBeenCalled()
  })
})
