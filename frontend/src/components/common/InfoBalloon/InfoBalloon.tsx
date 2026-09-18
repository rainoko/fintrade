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
        <Box sx={{ p: 2, maxWidth: 420 }}>
          <Typography variant="subtitle2" gutterBottom>
            {title}
          </Typography>
          {content}
        </Box>
      </Popover>
    </>
  )
}
