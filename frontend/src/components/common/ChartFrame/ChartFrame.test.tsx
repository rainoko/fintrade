import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ChartFrame, { CHART_FRAME_MAX_HEIGHT, CHART_FRAME_MIN_HEIGHT } from './ChartFrame'

/** Minimal stand-in for a chart pane: renders the maximize toggle inline, a
 * second always-present focusable control (mirroring a real pane's own
 * legend/`MetricHelp` buttons, which stay mounted inside the maximized
 * overlay alongside the toggle -- see `PriceChart`'s legend row), and a
 * canvas-shaped `div` whose height is driven by `canvasHeight`, plus the
 * resize handle directly beneath it -- the same shape every real
 * `PriceChart`/`OscillatorChart`/`VolumeIndicatorsChart`/`TrendStrengthChart`
 * call site uses. */
function TestChart({ label = 'Test chart', defaultHeight = 320 }) {
  return (
    <ChartFrame label={label} defaultHeight={defaultHeight}>
      {({ canvasHeight, isMaximized, maximizeToggle, resizeHandle }) => (
        <div>
          {maximizeToggle}
          <button type="button">{`${label} helper`}</button>
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

  it('resizes the canvas height via the keyboard (Arrow keys, Shift+Arrow, Home/End)', () => {
    render(<TestChart />)

    const handle = screen.getByRole('separator', { name: 'Resize Test chart height' })
    handle.focus()

    // ArrowDown pressed FIRST, before any drag/keyboard resize has set a
    // height yet, exercises the `resizedHeight ?? defaultHeight` fallback
    // (falls back to `defaultHeight` -- 320).
    fireEvent.keyDown(handle, { key: 'ArrowDown' })
    expect(screen.getByTestId('chart-canvas')).toHaveStyle({ height: '340px' })

    // Now `resizedHeight` is already a number, so this ArrowUp exercises
    // that same fallback's OTHER branch (uses the already-set height, not
    // `defaultHeight`).
    fireEvent.keyDown(handle, { key: 'ArrowUp' })
    expect(screen.getByTestId('chart-canvas')).toHaveStyle({ height: '320px' })

    // A second ArrowDown here (with `resizedHeight` already set) exercises
    // ArrowDown's own fallback's "already set" branch too.
    fireEvent.keyDown(handle, { key: 'ArrowDown', shiftKey: true })
    expect(screen.getByTestId('chart-canvas')).toHaveStyle({ height: '420px' })

    fireEvent.keyDown(handle, { key: 'End' })
    expect(screen.getByTestId('chart-canvas')).toHaveStyle({
      height: `${CHART_FRAME_MAX_HEIGHT}px`,
    })

    fireEvent.keyDown(handle, { key: 'Home' })
    expect(screen.getByTestId('chart-canvas')).toHaveStyle({
      height: `${CHART_FRAME_MIN_HEIGHT}px`,
    })

    // A key this handler doesn't recognize is a deliberate no-op (falls
    // through every `if`/`else if` without matching).
    fireEvent.keyDown(handle, { key: 'a' })
    expect(screen.getByTestId('chart-canvas')).toHaveStyle({
      height: `${CHART_FRAME_MIN_HEIGHT}px`,
    })
  })

  it('falls back to defaultHeight for the keyboard-resize ArrowUp step when nothing has been resized yet', () => {
    render(<TestChart />)

    const handle = screen.getByRole('separator', { name: 'Resize Test chart height' })
    handle.focus()

    // ArrowUp pressed FIRST (a fresh component, `resizedHeight` still
    // `null`) exercises its own `resizedHeight ?? defaultHeight` fallback's
    // "nothing resized yet" branch -- the sibling test above only ever
    // presses ArrowUp after a prior ArrowDown has already set a height.
    fireEvent.keyDown(handle, { key: 'ArrowUp' })
    expect(screen.getByTestId('chart-canvas')).toHaveStyle({ height: '300px' })
  })

  it('exposes the resize handle as a focusable, value-reporting separator', () => {
    render(<TestChart />)

    const handle = screen.getByRole('separator', { name: 'Resize Test chart height' })
    expect(handle).toHaveAttribute('tabindex', '0')
    expect(handle).toHaveAttribute('aria-valuenow', '320')
    expect(handle).toHaveAttribute('aria-valuemin', String(CHART_FRAME_MIN_HEIGHT))
    expect(handle).toHaveAttribute('aria-valuemax', String(CHART_FRAME_MAX_HEIGHT))
  })

  it('traps Tab navigation inside the maximized overlay, never reaching another pane behind it', async () => {
    // Reproduces the exact bug reported against PR #373: maximizing one
    // chart pane must not let repeated Tab presses move focus onto a
    // DIFFERENT, non-maximized pane's own (visually hidden-behind-the-
    // overlay but still-focusable) maximize button. Chart A's overlay has
    // TWO focusable controls (the toggle + its always-present "helper"
    // button), which also exercises both the "wrap at the boundary" AND
    // "move normally between two interior-to-the-trap elements" branches.
    const user = userEvent.setup()
    render(
      <>
        <TestChart label="Chart A" />
        <TestChart label="Chart B" />
      </>,
    )

    await user.click(screen.getByRole('button', { name: 'View Chart A full screen' }))
    const dialog = screen.getByRole('dialog', { name: 'Chart A full screen' })

    for (let i = 0; i < 12; i += 1) {
      await user.tab()
      expect(dialog.contains(document.activeElement)).toBe(true)
      expect(document.activeElement).not.toBe(
        screen.getByRole('button', { name: 'View Chart B full screen' }),
      )
    }
  })

  it('traps Shift+Tab navigation inside the maximized overlay the same way', async () => {
    const user = userEvent.setup()
    render(
      <>
        <TestChart label="Chart A" />
        <TestChart label="Chart B" />
      </>,
    )

    await user.click(screen.getByRole('button', { name: 'View Chart A full screen' }))
    const dialog = screen.getByRole('dialog', { name: 'Chart A full screen' })

    for (let i = 0; i < 12; i += 1) {
      await user.tab({ shift: true })
      expect(dialog.contains(document.activeElement)).toBe(true)
      expect(document.activeElement).not.toBe(
        screen.getByRole('button', { name: 'View Chart B full screen' }),
      )
    }
  })

  it('restores focus to the control that opened it once the overlay closes', async () => {
    const user = userEvent.setup()
    render(<TestChart />)

    const openButton = screen.getByRole('button', { name: 'View Test chart full screen' })
    await user.click(openButton)
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await user.keyboard('{Escape}')

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(document.activeElement).toBe(openButton)
  })

  // frontend-chart-fullscreen-resize-followups checklist item: the window-
  // resize subscription used to stay registered for the component's whole
  // lifetime regardless of `isMaximized`, discarding the recomputed value
  // every render while not maximized -- now gated so the real listener is
  // only attached while maximized.
  it('does not subscribe to window resize while not maximized', () => {
    const addEventListenerSpy = vi.spyOn(window, 'addEventListener')

    render(<TestChart />)

    expect(
      addEventListenerSpy.mock.calls.some(([eventName]) => eventName === 'resize'),
    ).toBe(false)

    addEventListenerSpy.mockRestore()
  })

  it('subscribes to window resize only while maximized, and unsubscribes again on exit', async () => {
    const user = userEvent.setup()
    const addEventListenerSpy = vi.spyOn(window, 'addEventListener')
    const removeEventListenerSpy = vi.spyOn(window, 'removeEventListener')

    render(<TestChart />)

    await user.click(screen.getByRole('button', { name: 'View Test chart full screen' }))
    expect(
      addEventListenerSpy.mock.calls.filter(([eventName]) => eventName === 'resize'),
    ).toHaveLength(1)

    await user.click(screen.getByRole('button', { name: 'Exit full screen (Test chart)' }))
    expect(
      removeEventListenerSpy.mock.calls.filter(([eventName]) => eventName === 'resize'),
    ).toHaveLength(1)

    addEventListenerSpy.mockRestore()
    removeEventListenerSpy.mockRestore()
  })

  it('keeps the body scroll lock engaged while a second instance is still maximized', async () => {
    const user = userEvent.setup()
    render(
      <>
        <TestChart label="Chart A" />
        <TestChart label="Chart B" />
      </>,
    )

    await user.click(screen.getByRole('button', { name: 'View Chart A full screen' }))
    expect(document.body.style.overflow).toBe('hidden')

    await user.click(screen.getByRole('button', { name: 'View Chart B full screen' }))
    expect(document.body.style.overflow).toBe('hidden')

    // Closing the FIRST-opened instance (A) while B is still maximized must
    // not release the shared lock -- this is the exact out-of-open-order
    // sequence the PR #373 review's second blocking finding described.
    await user.click(screen.getByRole('button', { name: 'Exit full screen (Chart A)' }))
    expect(document.body.style.overflow).toBe('hidden')

    await user.click(screen.getByRole('button', { name: 'Exit full screen (Chart B)' }))
    expect(document.body.style.overflow).toBe('')
  })
})
