import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import { humanizeSnakeCase } from '../../../utils/format'
import { EXIT_FLAG_LABELS } from '../exitFlagLabels'

export interface ExitFlagChipsProps {
  /** A position's `exit_flags` (GET /api/portfolio/risk), e.g. `['stop_hit']`. */
  flags: string[]
}

/**
 * Renders a wrapping row of small Chips, one per `exit_flags` value, each
 * labeled via `EXIT_FLAG_LABELS`/`humanizeSnakeCase` — or an em dash when
 * `flags` is empty. Shared between RiskPanel's full per-position risk table
 * and SellFlaggedPositionsCard's dashboard sell-flag summary so the
 * Chip-list rendering itself (severity styling, tooltip, a new flag's
 * variant, ...) never drifts between the two the way the label map used to
 * before it was extracted into `exitFlagLabels.ts`.
 *
 * Kept in `features/portfolio/` rather than `components/common/`: like
 * `EXIT_FLAG_LABELS` itself, every value it renders is portfolio-risk domain
 * vocabulary, not a generic/presentational concern.
 */
export default function ExitFlagChips({ flags }: ExitFlagChipsProps) {
  if (flags.length === 0) {
    return <>—</>
  }

  return (
    <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', rowGap: 0.5 }}>
      {flags.map((flag) => (
        <Chip key={flag} label={humanizeSnakeCase(flag, EXIT_FLAG_LABELS)} size="small" />
      ))}
    </Stack>
  )
}
