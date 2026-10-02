import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ChartFrame, { CHART_FRAME_MAX_HEIGHT, CHART_FRAME_MIN_HEIGHT } from './ChartFrame'

/** Minimal stand-in for a chart pane: renders the maximize toggle inline
 * and a canvas-shaped `div` whose height is driven by `canvasHeight`, plus
 * the resize handle directly beneath it -- the same shape every real
 * `PriceChart`/`OscillatorChart`/`VolumeIndicatorsChart`/`TrendStrengthChart`
 * call site uses. */
function TestChart({ label = 'Test chart', defaultHeight = 320 }) {
  return (
    <ChartFrame label={label} defaultHeight={defaultHeight}>
      {({ canvasHeight, isMaximized, maximizeToggle, resizeHandle }) => (
        <div>
          {maximizeToggle}
          <div data-testid="maximized-state">{String(isMaximized)}</div>
          <div data-testid="chart-canvas" style={{ height: canvasHeight }} />
          {resizeHandle}
        </div>
      )}
    </ChartFrame>
  )
}

function dragHandle(deltaY: number) {
  const handle = screen.getByRole('separator', { name: 'Resize Test chart height' })
  fireEvent.pointerDown(handle, { pointerId: 1, clientY: 100 })
  fireEvent.pointerMove(handle, { pointerId: 1, clientY: 100 + deltaY })
  fireEvent.pointerUp(handle, { pointerId: 1, clientY: 100 + deltaY })
}

describe('ChartFrame', () => {
  beforeEach(() => {
    vi.stubGlobal('innerHeight', 900)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders at the default height, not maximized, with a resize handle', () => {
    render(<TestChart />)

    expect(screen.getByTestId('maximized-state')).toHaveTextContent('false')
    expect(screen.getByTestId('chart-canvas')).toHaveStyle({ height: '320px' })
    expect(
      screen.getByRole('separator', { name: 'Resize Test chart height' }),
    ).toBeInTheDocument()
  })

  it('toggles into and out of the full-screen dialog', async () => {
    const user = userEvent.setup()
    render(<TestChart />)

    await user.click(screen.getByRole('button', { name: 'View Test chart full screen' }))

    expect(screen.getByRole('dialog', { name: 'Test chart full screen' })).toBeInTheDocument()
    expect(screen.getByTestId('maximized-state')).toHaveTextContent('true')
    // No resize handle while maximized -- the full-screen height comes from
    // the viewport, not the drag state.
    expect(
      screen.queryByRole('separator', { name: 'Resize Test chart height' }),
    ).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Exit full screen (Test chart)' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByTestId('maximized-state')).toHaveTextContent('false')
  })

  it('closes via the overlay`s own Escape handling', async () => {
    const user = userEvent.setup()
    render(<TestChart />)

    await user.click(screen.getByRole('button', { name: 'View Test chart full screen' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await user.keyboard('{Escape}')

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('ignores a non-Escape key while maximized', async () => {
    const user = userEvent.setup()
    render(<TestChart />)

    await user.click(screen.getByRole('button', { name: 'View Test chart full screen' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await user.keyboard('a')

    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('locks and restores body scroll across a maximize/restore cycle', async () => {
    const user = userEvent.setup()
    render(<TestChart />)

    expect(document.body.style.overflow).toBe('')

    await user.click(screen.getByRole('button', { name: 'View Test chart full screen' }))
    expect(document.body.style.overflow).toBe('hidden')

    await user.click(screen.getByRole('button', { name: 'Exit full screen (Test chart)' }))
    expect(document.body.style.overflow).toBe('')
  })

  it('computes the maximized canvas height from the current viewport, clamped to the max', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('innerHeight', 2000)
    render(<TestChart />)

    await user.click(screen.getByRole('button', { name: 'View Test chart full screen' }))

    expect(screen.getByTestId('chart-canvas')).toHaveStyle({
      height: `${CHART_FRAME_MAX_HEIGHT}px`,
    })
  })

  it('clamps a very short viewport to the minimum maximized height', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('innerHeight', 300)
    render(<TestChart />)

    await user.click(screen.getByRole('button', { name: 'View Test chart full screen' }))

    expect(screen.getByTestId('chart-canvas')).toHaveStyle({
      height: `${CHART_FRAME_MIN_HEIGHT}px`,
    })
  })

  it('recomputes the maximized height on a window resize while open', async () => {
    const user = userEvent.setup()
    render(<TestChart />)

    await user.click(screen.getByRole('button', { name: 'View Test chart full screen' }))
    expect(screen.getByTestId('chart-canvas')).toHaveStyle({ height: '680px' })

    vi.stubGlobal('innerHeight', 600)
    fireEvent(window, new Event('resize'))

    expect(screen.getByTestId('chart-canvas')).toHaveStyle({ height: '380px' })
  })

  it('drag-resizes the canvas height by the pointer delta', () => {
    render(<TestChart />)

    dragHandle(150)

    expect(screen.getByTestId('chart-canvas')).toHaveStyle({ height: '470px' })
  })

  it('clamps a drag past the maximum height', () => {
    render(<TestChart />)

    dragHandle(10_000)

    expect(screen.getByTestId('chart-canvas')).toHaveStyle({
      height: `${CHART_FRAME_MAX_HEIGHT}px`,
    })
  })

  it('clamps a drag past the minimum height', () => {
    render(<TestChart />)

    dragHandle(-10_000)

    expect(screen.getByTestId('chart-canvas')).toHaveStyle({
      height: `${CHART_FRAME_MIN_HEIGHT}px`,
    })
  })

  it('ignores a pointermove from a different pointer than the one that started the drag', () => {
    render(<TestChart />)

    const handle = screen.getByRole('separator', { name: 'Resize Test chart height' })
    fireEvent.pointerDown(handle, { pointerId: 1, clientY: 100 })
    fireEvent.pointerMove(handle, { pointerId: 2, clientY: 400 })

    expect(screen.getByTestId('chart-canvas')).toHaveStyle({ height: '320px' })
  })

  it('ignores a pointermove once the drag has ended', () => {
    render(<TestChart />)

    const handle = screen.getByRole('separator', { name: 'Resize Test chart height' })
    fireEvent.pointerDown(handle, { pointerId: 1, clientY: 100 })
    fireEvent.pointerUp(handle, { pointerId: 1, clientY: 100 })
    fireEvent.pointerMove(handle, { pointerId: 1, clientY: 400 })

    expect(screen.getByTestId('chart-canvas')).toHaveStyle({ height: '320px' })
  })

  it('ignores a pointerup from a different pointer than the one dragging', () => {
    render(<TestChart />)

    const handle = screen.getByRole('separator', { name: 'Resize Test chart height' })
    fireEvent.pointerDown(handle, { pointerId: 1, clientY: 100 })
    fireEvent.pointerUp(handle, { pointerId: 2, clientY: 100 })
    fireEvent.pointerMove(handle, { pointerId: 1, clientY: 250 })

    expect(screen.getByTestId('chart-canvas')).toHaveStyle({ height: '470px' })
  })

  it('persists the drag-resized height when toggling in and out of full screen', async () => {
    const user = userEvent.setup()
    render(<TestChart />)

    dragHandle(50)
    expect(screen.getByTestId('chart-canvas')).toHaveStyle({ height: '370px' })

    await user.click(screen.getByRole('button', { name: 'View Test chart full screen' }))
    await user.click(screen.getByRole('button', { name: 'Exit full screen (Test chart)' }))

    expect(screen.getByTestId('chart-canvas')).toHaveStyle({ height: '370px' })
  })
})
