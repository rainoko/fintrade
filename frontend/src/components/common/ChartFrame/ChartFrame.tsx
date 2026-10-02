import FullscreenIcon from '@mui/icons-material/FullscreenOutlined'
import FullscreenExitIcon from '@mui/icons-material/FullscreenExitOutlined'
import Box from '@mui/material/Box'
import IconButton from '@mui/material/IconButton'
import Tooltip from '@mui/material/Tooltip'
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react'

/**
 * Clamp bounds for both the drag-resize handle and (indirectly, via
 * `clampHeight`) the full-screen view's computed height -- see
 * `frontend-chart-fullscreen-resize`'s `decisions` entry for how these were
 * picked: 200px is short enough to meaningfully shrink a pane but still
 * tall enough to read candles/lines on, 900px is comfortably larger than
 * every existing `CHART_HEIGHT` (320/420) without being so tall a single
 * pane could exceed most monitors' usable height before a drag even reaches
 * full screen.
 */
export const CHART_FRAME_MIN_HEIGHT = 200
export const CHART_FRAME_MAX_HEIGHT = 900

/** Keyboard step size (px) for the drag-resize handle's Arrow-key
 * equivalent -- see `handleResizeKeyDown` below. Shift+Arrow steps 5x this. */
const RESIZE_KEYBOARD_STEP_PX = 20

/**
 * Rough headroom (px) reserved in the full-screen overlay for whatever a
 * given chart pane renders above/around its own canvas (range/interval
 * controls, legend rows, overlay padding) -- deliberately approximate
 * rather than measured per pane (the four current panes' own header content
 * varies in height), since the overlay itself scrolls (`overflow: 'auto'`
 * below) if the real content is taller than this estimate leaves room for.
 * See this task's `decisions` entry for why an approximate constant plus
 * scrolling was chosen over precisely measuring each pane's own chrome.
 */
const MAXIMIZED_CHROME_ALLOWANCE_PX = 220

function clampHeight(value: number): number {
  return Math.min(CHART_FRAME_MAX_HEIGHT, Math.max(CHART_FRAME_MIN_HEIGHT, value))
}

function computeMaximizedHeight(): number {
  return clampHeight(window.innerHeight - MAXIMIZED_CHROME_ALLOWANCE_PX)
}

/**
 * Module-level open-overlay stack/counter (mirrors MUI's own `ModalManager`
 * approach, named explicitly in the PR #373 review finding this fixes) --
 * NOT a per-instance snapshot. Every `ChartFrame` instance that maximizes
 * calls `acquireBodyScrollLock` and every one that un-maximizes/unmounts
 * calls the returned release function; only the FIRST acquire actually
 * locks `document.body.style.overflow`, and only the release that brings
 * the shared count back to zero restores it. This is what makes the fix
 * correct for two simultaneously-maximized instances closed out of open
 * order (chart A opens first, chart B opens second, chart A closes first):
 * a per-instance `previousBodyOverflow` snapshot could have A's close
 * restore `overflow` to '' while B is still rendered as a full-viewport
 * overlay, re-enabling page scroll underneath it. With a shared counter, A's
 * close only decrements 2 -> 1 and leaves the lock in place; only B's later
 * close (1 -> 0) actually restores the original value.
 */
let openOverlayCount = 0
let bodyOverflowBeforeFirstOverlay: string | null = null

function acquireBodyScrollLock(): () => void {
  if (openOverlayCount === 0) {
    bodyOverflowBeforeFirstOverlay = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  }
  openOverlayCount += 1
  // No double-release guard: the sole caller is this component's own
  // maximize `useEffect`, whose cleanup React invokes at most once per
  // `isMaximized` transition (including under StrictMode's dev-only
  // double-invoke, which still pairs each setup with exactly one cleanup
  // before the next setup) -- an unreachable guard here would be dead code
  // this suite's coverage gate would then have to carve an exception for.
  return () => {
    openOverlayCount -= 1
    if (openOverlayCount === 0) {
      // `?? ''` is a type-narrowing safety net, not a reachable branch in
      // practice: `bodyOverflowBeforeFirstOverlay` is always assigned a
      // (possibly empty) string above in the same acquire/release pairing
      // that leads here, right before the only increment that could bring
      // `openOverlayCount` back down to 0.
      /* v8 ignore next */
      document.body.style.overflow = bodyOverflowBeforeFirstOverlay ?? ''
      bodyOverflowBeforeFirstOverlay = null
    }
  }
}

/** Selector for the standard set of natively-focusable/tabbable elements --
 * used by the focus trap below to find what Tab/Shift+Tab should cycle
 * through inside the maximized overlay. Mirrors the element set MUI's own
 * `Modal`/`unstable_trapFocus` uses. Deliberately does NOT additionally
 * filter by computed visibility/`getClientRects` -- the bug this fixes
 * (PR #373 review) was a DIFFERENT chart pane's maximize button being
 * genuinely `display:flex`/`visibility:visible` (just stacked behind this
 * overlay by z-index, not hidden by any CSS this trap could detect), so a
 * visibility check wouldn't have told the two cases apart anyway. Scoping
 * the query to `container` (this overlay's own subtree) is what actually
 * fixes it: elements belonging to a different, non-maximized `ChartFrame`
 * instance are never inside this instance's own `frameRef` subtree, so they
 * never appear in this list regardless of their visibility. jsdom (this
 * component's own test environment) doesn't implement layout, so a
 * getClientRects/offsetParent-based filter would be unreliable in tests
 * even if it were otherwise desirable here.
 */
const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
}

/**
 * Subscribes `onStoreChange` to the browser's own `resize` event --
 * `useSyncExternalStore`'s intended use case (reading external, mutable
 * browser state), chosen over a `useEffect` + `useState` pair specifically
 * to avoid synchronously calling `setState` from inside an effect body
 * (flagged by this repo's `eslint-plugin-react-hooks` `set-state-in-effect`
 * rule — see this task's `decisions` entry): there's no React state to
 * "set" here at all, just a read of `window.innerHeight` that this hook
 * re-runs whenever the browser reports a resize.
 */
function subscribeToWindowResize(onStoreChange: () => void): () => void {
  window.addEventListener('resize', onStoreChange)
  return () => window.removeEventListener('resize', onStoreChange)
}

export interface ChartFrameRenderArgs {
  /** Current canvas height (px) -- feed this straight into the chart
   * container `Box`'s `sx.height` in place of the pane's own fixed
   * `CHART_HEIGHT` constant. Lightweight Charts' own `autoSize: true`
   * (`utils/chart.ts`'s `createBaseChart`) picks up the resulting container
   * size change itself; nothing here calls `chart.resize()`. */
  canvasHeight: number
  /** Whether the pane is currently shown in the full-screen overlay. */
  isMaximized: boolean
  /** Icon button toggling full screen on/off -- place it in the pane's own
   * controls/legend row. Reused as the overlay's own exit affordance (it
   * shows "exit full screen" once `isMaximized` is true), so callers only
   * need to render it once, not duplicate a second close control. */
  maximizeToggle: ReactNode
  /** Drag-to-resize handle -- place it directly beneath the chart canvas
   * `Box`. `null` while maximized (the full-screen height is computed from
   * the viewport, not the drag state -- dragging would have nothing
   * meaningful to do). */
  resizeHandle: ReactNode
}

export interface ChartFrameProps {
  /** Short, human-readable name for this pane (e.g. "Price chart",
   * "Oscillators"), used for the maximize/restore toggle's accessible name
   * and the full-screen overlay's own `aria-label`. */
  label: string
  /** The canvas height used before any drag-resize and while not
   * maximized -- each pane's own existing `CHART_HEIGHT` constant. */
  defaultHeight: number
  children: (args: ChartFrameRenderArgs) => ReactNode
}

/**
 * Shared "a chart pane that can enlarge" wrapper (frontend-chart-fullscreen-
 * resize) -- a full-screen toggle AND an independent drag-to-resize height
 * handle, per this task's `decisions` entry (the user's own phrasing left
 * both affordances on the table rather than picking one). Domain-agnostic
 * (Frontend.md §3's common/-vs-feature-specific placement test): it takes a
 * label string and a height, with zero reference to tickers/indicators/
 * signals, and every one of the four chart panes needs the exact same
 * behavior -- see this task's `decisions` entry for why a shared `common/`
 * wrapper was chosen over a per-component implementation across
 * `PriceChart`/`OscillatorChart`/`VolumeIndicatorsChart`/`TrendStrengthChart`.
 *
 * Takes a render-prop `children` rather than wrapping a fixed children
 * subtree: each of the four chart panes needs the current `canvasHeight`
 * threaded into its own chart-container `Box`'s `sx.height` (replacing its
 * own `CHART_HEIGHT` constant) and the `maximizeToggle` placed inline within
 * its own existing controls/legend row (`PriceChart`'s range/interval
 * `ToggleButtonGroup` row; the other three panes' plain title row) -- a
 * render prop lets each caller decide exactly where those two things land
 * in its own markup without this component needing to know anything about
 * that markup's shape.
 *
 * Full screen is a CSS-only "maximize within the page" overlay: a single
 * `Box` that's ALWAYS rendered at the same position in the React tree
 * (never conditionally swapped for e.g. a `Dialog`/`Modal`), with only its
 * `sx`/ARIA props varying between the in-flow and maximized states. This is
 * a deliberate, load-bearing choice, not just a style preference -- see this
 * task's `decisions` entry: an earlier version of this component used MUI's
 * `Dialog` (portaled, mount-on-`open`), which looked simpler and came with a
 * built-in scroll lock/Escape handling/focus trap for free, but broke the
 * actual chart it was wrapping. `PriceChart`/`OscillatorChart`/etc. each
 * create their Lightweight Charts instance in a `useEffect` keyed only on
 * their own query data (`historyQuery.data`/`indicatorsQuery.data`), NOT on
 * this component's maximize state, on the assumption that their own
 * `containerRef` div stays mounted for the chart's whole lifetime. Wrapping
 * `content` in a conditionally-rendered `Dialog` changes `content`'s
 * ancestor chain (nothing vs. `Dialog > DialogContent`) between renders,
 * which React treats as the child subtree moving to a different position in
 * the tree -- it unmounts the OLD subtree (including the chart's own
 * container div, destroying the DOM node `containerRef` pointed at) and
 * mounts a brand NEW one, but the chart-creation effect doesn't re-run
 * (its own deps didn't change), so the newly-mounted container is left with
 * no chart in it at all. Confirmed via a real-browser Playwright walkthrough
 * against the running dev server (not just the mocked `lightweight-charts`
 * unit tests, which never exercise a real container element and so never
 * caught this): the maximized dialog opened, but its canvas never
 * materialized. A single persistent `Box` whose OWN `sx` toggles between
 * normal in-flow layout and `{ position: 'fixed', inset: 0, ... }` sidesteps
 * the whole problem -- the chart's container div is never unmounted, Only
 * its ANCESTOR's CSS position changes, which is exactly the kind of
 * container-size change Lightweight Charts' `autoSize`/`ResizeObserver`
 * already handles on its own.
 *
 * The tradeoff against the native browser Fullscreen API
 * (`element.requestFullscreen()`, the other option this task's `decisions`
 * entry weighs) is the same either way: no OS-level fullscreen chrome, no
 * user-gesture-call-stack/cross-browser quirks to account for, at the cost
 * of not being literal fullscreen -- this is a "maximize within the page"
 * overlay, covering the viewport via CSS rather than the OS's own
 * fullscreen surface. Losing MUI `Dialog`'s free scroll-lock/Escape-
 * handling/focus-placement (now that `Dialog` itself can't be used) is
 * handled by this component directly instead, in the one `useEffect` below.
 *
 * The drag-resize height is plain `useState`, not persisted to
 * `localStorage` -- see this task's `decisions` entry: a dragged height is
 * treated as a transient viewing preference for the current page visit, not
 * a durable per-chart setting worth the added complexity of a storage key
 * per pane (4 panes x potentially per-ticker) and a migration story if the
 * key shape ever changed. It naturally survives a ticker change within the
 * same mounted chart component (ordinary React state) and resets on an
 * actual remount (page reload, or navigating away and back if the route
 * unmounts the chart).
 */
export default function ChartFrame({ label, defaultHeight, children }: ChartFrameProps) {
  const [isMaximized, setIsMaximized] = useState(false)
  const [resizedHeight, setResizedHeight] = useState<number | null>(null)
  const dragStateRef = useRef<{ pointerId: number; startY: number; startHeight: number } | null>(
    null,
  )
  const frameRef = useRef<HTMLDivElement | null>(null)

  // Full-screen height tracks the actual viewport live via
  // `useSyncExternalStore` (see `subscribeToWindowResize`'s own doc comment
  // for why this is a sync-external-store subscription rather than a
  // `useEffect` + `useState` pair) -- a narrow/mobile viewport (this task's
  // checklist item 4) gets a correspondingly shorter canvas, and a resize/
  // orientation change while already maximized keeps it current too. Reads
  // `window.innerHeight` unconditionally (not just while maximized): cheap,
  // and keeps this one subscription active for the component's whole
  // lifetime rather than subscribing/unsubscribing on every maximize toggle.
  const maximizedHeight = useSyncExternalStore(
    subscribeToWindowResize,
    computeMaximizedHeight,
    computeMaximizedHeight,
  )

  // Body scroll lock (via the shared, stack-counted
  // `acquireBodyScrollLock` -- see its own doc comment for why a per-
  // instance snapshot was wrong) + Escape-to-exit + a real focus trap +
  // initial focus placement/focus restoration while maximized -- the
  // "for free" behaviors a `Dialog` would otherwise provide, reimplemented
  // directly since this component can't use `Dialog` itself (see this
  // component's own doc comment on why). `setIsMaximized` is called from
  // the `keydown` *callback*, not synchronously in the effect body itself,
  // so this doesn't trip the same `react-hooks/set-state-in-effect` rule
  // `maximizedHeight` above avoids a different way.
  //
  // Focus trap (PR #373 review's first blocking finding): Tab/Shift+Tab is
  // intercepted at the `window` level while maximized and, whenever it
  // would move focus to something outside this instance's own `frameRef`
  // subtree (including wrapping past the first/last focusable descendant,
  // or focus starting outside the trap entirely -- e.g. nothing inside it
  // happens to be focusable), redirected back to the first or last
  // focusable element inside the overlay instead. Scoping
  // `getFocusableElements` to `frameRef.current` is what actually fixes the
  // reported bug: a DIFFERENT, non-maximized `ChartFrame` instance's own
  // maximize button lives in a different `frameRef` subtree entirely, so it
  // can never be a candidate this trap would tab to, regardless of it still
  // being visually `display:flex`/`visibility:visible` behind this overlay.
  useEffect(() => {
    if (!isMaximized) {
      return
    }
    const releaseBodyScrollLock = acquireBodyScrollLock()
    const previouslyFocusedElement = document.activeElement as HTMLElement | null
    frameRef.current?.focus()
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsMaximized(false)
        return
      }
      if (event.key !== 'Tab') {
        return
      }
      const container = frameRef.current
      // `frameRef` is attached to this very overlay `Box`, which is always
      // mounted and rendered by the time this listener can fire (it's only
      // ever added once `isMaximized` is already true and the ref is
      // populated during commit, before effects run) -- unreachable in
      // practice, kept purely so TypeScript narrows `container` from
      // `HTMLDivElement | null` below.
      /* v8 ignore next 3 */
      if (!container) {
        return
      }
      const focusable = getFocusableElements(container)
      // Every real call site renders at least the maximize/exit toggle
      // button inside the overlay, so an empty `focusable` list shouldn't
      // occur in practice -- kept as a safety net (send focus back to the
      // container itself rather than letting it escape) in case a future
      // caller's `children` render prop ever omits every focusable control.
      /* v8 ignore next 4 */
      if (focusable.length === 0) {
        event.preventDefault()
        container.focus()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement
      // `indexOf` (rather than an `instanceof`/`.contains` check) is what
      // correctly covers THREE cases as "needs redirecting" in one go: focus
      // on an element outside this container entirely (the originally
      // reported bug), focus still sitting on the dialog container itself
      // (tabIndex -1, so never a member of `focusable` -- true right after
      // the initial `container.focus()` above, before any Tab has been
      // pressed yet), and focus on the last/first focusable member when
      // tabbing off the matching end (the ordinary wrap-around case).
      // The `: -1` fallback is a type-narrowing safety net for
      // `document.activeElement`'s `Element | null` type, not a reachable
      // branch under normal use: this listener only ever runs while
      // `frameRef.current?.focus()` (above) has already placed focus
      // somewhere inside the document (an `HTMLElement`), so
      // `document.activeElement` is never `null`/a non-HTML `Element` by
      // the time a `Tab` keydown can reach here.
      /* v8 ignore next */
      const activeIndex = active instanceof HTMLElement ? focusable.indexOf(active) : -1
      if (event.shiftKey) {
        if (activeIndex <= 0) {
          event.preventDefault()
          last.focus()
        }
      } else if (activeIndex === -1 || activeIndex === focusable.length - 1) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      releaseBodyScrollLock()
      window.removeEventListener('keydown', handleKeyDown)
      // Restore focus to whatever triggered the maximize (the pane's own
      // maximize button) rather than leaving it on the now-unmounted-from-
      // view dialog container or wherever it happened to land last.
      previouslyFocusedElement?.focus()
    }
  }, [isMaximized])

  const handlePointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      event.preventDefault()
      dragStateRef.current = {
        pointerId: event.pointerId,
        startY: event.clientY,
        startHeight: resizedHeight ?? defaultHeight,
      }
      // jsdom (this component's own test environment) doesn't implement
      // `setPointerCapture` -- guarded rather than assumed, so the drag
      // still works in every real browser without needing a feature-detect
      // branch duplicated at every call site.
      event.currentTarget.setPointerCapture?.(event.pointerId)
    },
    [defaultHeight, resizedHeight],
  )

  const handlePointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const dragState = dragStateRef.current
    if (!dragState || dragState.pointerId !== event.pointerId) {
      return
    }
    const delta = event.clientY - dragState.startY
    setResizedHeight(clampHeight(dragState.startHeight + delta))
  }, [])

  const endDrag = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (dragStateRef.current?.pointerId === event.pointerId) {
      dragStateRef.current = null
    }
  }, [])

  // Keyboard equivalent for the drag-resize handle (follow-up from PR #373's
  // review, folded into this round rather than left deferred): the WAI-ARIA
  // separator/window-splitter pattern expects a focusable separator to
  // support Arrow keys. ArrowDown/ArrowUp step by `RESIZE_KEYBOARD_STEP_PX`
  // (a larger step while Shift is held); Home/End jump straight to the
  // clamped min/max -- both WAI-ARIA-recommended for this pattern and a
  // quick way to reach either bound without many repeated key presses.
  const handleResizeKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLDivElement>) => {
      const step = event.shiftKey ? RESIZE_KEYBOARD_STEP_PX * 5 : RESIZE_KEYBOARD_STEP_PX
      if (event.key === 'ArrowDown') {
        event.preventDefault()
        setResizedHeight(clampHeight((resizedHeight ?? defaultHeight) + step))
      } else if (event.key === 'ArrowUp') {
        event.preventDefault()
        setResizedHeight(clampHeight((resizedHeight ?? defaultHeight) - step))
      } else if (event.key === 'Home') {
        event.preventDefault()
        setResizedHeight(CHART_FRAME_MIN_HEIGHT)
      } else if (event.key === 'End') {
        event.preventDefault()
        setResizedHeight(CHART_FRAME_MAX_HEIGHT)
      }
    },
    [defaultHeight, resizedHeight],
  )

  const toggleMaximized = useCallback(() => setIsMaximized((value) => !value), [])

  const maximizeToggle = (
    <Tooltip title={isMaximized ? 'Exit full screen' : `View ${label} full screen`}>
      <IconButton
        size="small"
        aria-label={isMaximized ? `Exit full screen (${label})` : `View ${label} full screen`}
        onClick={toggleMaximized}
      >
        {isMaximized ? (
          <FullscreenExitIcon fontSize="small" />
        ) : (
          <FullscreenIcon fontSize="small" />
        )}
      </IconButton>
    </Tooltip>
  )

  const resizeHandle = isMaximized ? null : (
    <Box
      role="separator"
      aria-orientation="horizontal"
      aria-label={`Resize ${label} height`}
      aria-valuenow={resizedHeight ?? defaultHeight}
      aria-valuemin={CHART_FRAME_MIN_HEIGHT}
      aria-valuemax={CHART_FRAME_MAX_HEIGHT}
      tabIndex={0}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onKeyDown={handleResizeKeyDown}
      sx={{
        width: '100%',
        // A touch-friendly 24px hit target (this task's checklist item 4)
        // even though the visible grip line drawn inside it is much
        // thinner -- see the nested Box below.
        height: 24,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'ns-resize',
        touchAction: 'none',
        '&:hover .chart-frame-resize-grip': { bgcolor: 'text.secondary' },
      }}
    >
      <Box
        className="chart-frame-resize-grip"
        sx={{ width: 40, height: 4, borderRadius: 2, bgcolor: 'divider' }}
      />
    </Box>
  )

  const canvasHeight = isMaximized ? maximizedHeight : (resizedHeight ?? defaultHeight)

  const content = children({ canvasHeight, isMaximized, maximizeToggle, resizeHandle })

  return (
    <Box
      ref={frameRef}
      // Only ever present while maximized -- an in-flow (non-maximized)
      // pane isn't itself a dialog, it's just a normal section of the page.
      role={isMaximized ? 'dialog' : undefined}
      aria-modal={isMaximized ? true : undefined}
      aria-label={isMaximized ? `${label} full screen` : undefined}
      tabIndex={isMaximized ? -1 : undefined}
      sx={
        isMaximized
          ? {
              position: 'fixed',
              inset: 0,
              zIndex: (theme) => theme.zIndex.modal,
              bgcolor: 'background.paper',
              overflow: 'auto',
              p: 2,
              outline: 'none',
            }
          : undefined
      }
    >
      {content}
    </Box>
  )
}
