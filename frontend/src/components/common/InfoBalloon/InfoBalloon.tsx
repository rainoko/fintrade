import Box from '@mui/material/Box'
import ButtonBase from '@mui/material/ButtonBase'
import Popover from '@mui/material/Popover'
import Typography from '@mui/material/Typography'
import type { ReactNode } from 'react'
import { useId, useState } from 'react'

export interface InfoBalloonProps {
  /** Accessible name for the clickable trigger, e.g. "Why BUY?". */
  triggerAriaLabel: string
  /** Popover heading. */
  title: string
  /** Popover body -- any renderable explanation content. */
  content: ReactNode
  /** The clickable element that opens the balloon (e.g. a SignalBadge). */
  children: ReactNode
}

/** The title + content chrome shared by `InfoBalloon` (below) and
 * `AnchoredInfoBalloon` -- kept as one small internal helper so the two
 * balloon variants can never visually drift apart. */
function BalloonContent({ title, content }: { title: string; content: ReactNode }) {
  return (
    <Box sx={{ p: 2, maxWidth: 420 }}>
      <Typography variant="subtitle2" gutterBottom>
        {title}
      </Typography>
      {content}
    </Box>
  )
}

/**
 * Generic "click a trigger element, get a balloon (Popover) with an
 * explanation" pattern -- takes only presentation props (labels/content as
 * plain strings/ReactNode) and no domain knowledge of what it's explaining,
 * so it lives in `components/common/` rather than under any
 * `features/<domain>/` folder (Frontend.md §3's placement test). A Popover
 * (anchored balloon), not a `Dialog` modal: every current caller's content
 * is a short, bounded explanation (a headline plus a handful of
 * condition/value lines) that reads fine inline near what it's explaining,
 * not a form or a long document that would need the whole viewport's focus
 * -- see the frontend-signal-why-explanation task's `decisions` entry for
 * the full balloon-vs-modal reasoning.
 *
 * The trigger is wrapped in a `ButtonBase` (not `cloneElement` onto
 * `children` directly) so this works with any child -- a `Chip`, plain
 * text, an icon -- without needing that child to forward an `onClick`/
 * `ref` itself.
 */
export default function InfoBalloon({
  triggerAriaLabel,
  title,
  content,
  children,
}: InfoBalloonProps) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)
  const popoverId = useId()
  const open = Boolean(anchorEl)

  return (
    <>
      <ButtonBase
        onClick={(event) => setAnchorEl(event.currentTarget)}
        aria-label={triggerAriaLabel}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-describedby={open ? popoverId : undefined}
        sx={{ borderRadius: 1 }}
      >
        {children}
      </ButtonBase>
      <Popover
        id={popoverId}
        open={open}
        anchorEl={anchorEl}
        onClose={() => setAnchorEl(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
      >
        <BalloonContent title={title} content={content} />
      </Popover>
    </>
  )
}

export interface AnchoredInfoBalloonProps {
  /** Whether the balloon is currently open -- externally controlled, unlike
   * `InfoBalloon`'s own internal open/close state, since this variant has
   * no trigger element of its own to own that state (see this component's
   * own doc comment). */
  open: boolean
  /**
   * Page (`clientX`/`clientY`-relative) coordinates to anchor the balloon
   * at, or `null` when nothing has been clicked yet -- passed straight
   * through to MUI `Popover`'s `anchorPosition` (`anchorReference=
   * "anchorPosition"`). `open` is treated as `false` whenever this is
   * `null`, regardless of the `open` prop, so a caller can't accidentally
   * render an anchorless popover.
   */
  anchorPosition: { top: number; left: number } | null
  onClose: () => void
  /** Popover heading, same role as `InfoBalloon`'s `title`. */
  title: string
  /** Popover body, same role as `InfoBalloon`'s `content`. */
  content: ReactNode
  /** Accessible name for the popover itself (`aria-label`) -- required here,
   * unlike `InfoBalloon`, since there's no trigger button of this variant's
   * own for assistive tech to already have announced before the popover
   * opens. */
  ariaLabel: string
}

/**
 * `InfoBalloon`'s same title+content balloon (`BalloonContent` above), but
 * opened externally by page coordinates rather than by wrapping a clickable
 * DOM trigger element -- for a trigger that isn't a real DOM node at all,
 * such as a marker drawn on a `<canvas>` by a charting library (Lightweight
 * Charts' series-marker plugin has no DOM element of its own to attach a
 * `ButtonBase`/`onClick` to; it only reports a click's page coordinates via
 * `chart.subscribeClick`). See `PriceChart.tsx`'s/`OscillatorChart.tsx`'s
 * divergence-marker click handling (frontend-divergence-markers) for the
 * one real caller today.
 *
 * Deliberately a second export from this same file/folder, not a
 * `features/stocks/`-local component: the balloon-positioning-by-
 * coordinates behavior itself is exactly as domain-agnostic as
 * `InfoBalloon`'s own click-a-trigger-child behavior -- only *when* a caller
 * has coordinates to open it at (a canvas click, a context-menu event, ...)
 * is domain-specific, and that stays entirely in the caller. Sharing
 * `BalloonContent` (rather than each maintaining its own copy of the
 * `Box`/`Typography` chrome) keeps the two variants' visual presentation
 * from silently drifting apart.
 */
export function AnchoredInfoBalloon({
  open,
  anchorPosition,
  onClose,
  title,
  content,
  ariaLabel,
}: AnchoredInfoBalloonProps) {
  return (
    <Popover
      open={open && anchorPosition !== null}
      anchorReference="anchorPosition"
      anchorPosition={anchorPosition ?? undefined}
      onClose={onClose}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
      transformOrigin={{ vertical: 'top', horizontal: 'left' }}
      slotProps={{ paper: { 'aria-label': ariaLabel } }}
    >
      <BalloonContent title={title} content={content} />
    </Popover>
  )
}
