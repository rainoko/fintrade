import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogContentText from '@mui/material/DialogContentText'
import DialogTitle from '@mui/material/DialogTitle'
import FormControl from '@mui/material/FormControl'
import InputLabel from '@mui/material/InputLabel'
import MenuItem from '@mui/material/MenuItem'
import Select, { type SelectChangeEvent } from '@mui/material/Select'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'
import { useState, type FormEvent } from 'react'
import type { TradeApgarIn, TradeApgarQuestionOut } from '../../../api/portfolio'
import DataTable, { type DataTableColumn } from '../../../components/common/DataTable/DataTable'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import { humanizeSnakeCase } from '../../../utils/format'
import { useGuardedDialogClose } from '../hooks/useGuardedDialogClose'
import { useResetOnSubjectChange } from '../hooks/useResetOnSubjectChange'
import { useScoreTradeApgar } from '../hooks/useScoreTradeApgar'

type FalseBreakoutStatus = TradeApgarIn['false_breakout_status']
type Perfection = TradeApgarIn['perfection']

export interface TradeApgarDialogProps {
  /**
   * Ticker to score (e.g. the one currently being viewed on the Stock Detail
   * page), or `null` to keep the dialog closed — `open` is derived from this
   * rather than a separate boolean, mirroring `FollowUpReviewDialog`'s own
   * "the subject drives openness" pattern, so a caller can't accidentally
   * render the dialog open with no ticker to score.
   */
  ticker: string | null
  onClose: () => void
}

const FALSE_BREAKOUT_OPTIONS: Array<{ value: FalseBreakoutStatus; label: string }> = [
  { value: 'none', label: 'None' },
  { value: 'already_happened', label: 'Already happened' },
  { value: 'on_the_verge', label: 'On the verge' },
]

const PERFECTION_OPTIONS: Array<{ value: Perfection; label: string }> = [
  { value: 'neither', label: 'Neither timeframe looks ideal' },
  { value: 'one', label: 'One timeframe looks ideal' },
  { value: 'both', label: 'Both timeframes look ideal' },
]

// TradeApgarQuestionOut.value is a raw API value: FalseBreakoutStatusIn/
// PerfectionIn's own snake_case literals for the two manual questions (echoed
// straight back from what the caller submitted), or Impulse's own
// 'GREEN'/'RED'/'BLUE'/`'above_value'/'in_value_zone'/'below_value'` for the
// three auto questions. Reuse this dialog's own FALSE_BREAKOUT_OPTIONS/
// PERFECTION_OPTIONS label maps for the manual values (bespoke wording
// matching their own <Select> options) and fall back to humanizeSnakeCase's
// generic underscores-to-spaces/capitalize for the auto ones, the same
// convention ScreensPanel/SignalSummary already use elsewhere for a
// snake_case-ish domain value (frontend-trade-apgar-followups).
const VALUE_LABELS: Record<string, string> = Object.fromEntries(
  [...FALSE_BREAKOUT_OPTIONS, ...PERFECTION_OPTIONS].map((option) => [option.value, option.label]),
)

const columns: DataTableColumn<TradeApgarQuestionOut>[] = [
  { key: 'label', header: 'Question' },
  { key: 'value', header: 'Value', render: (row) => humanizeSnakeCase(row.value, VALUE_LABELS) },
  { key: 'score', header: 'Score', align: 'right' },
]

/**
 * Pre-trade "Trade Apgar" go/no-go form dialog (Elder ch. 58,
 * docs/architecture/API.md's `POST /api/portfolio/trade-apgar`) — the
 * pre-trade counterpart to `FollowUpReviewDialog`'s after-the-fact review.
 * Feature component (not `common/`): it renders `TradeApgarQuestionOut` rows
 * and a ticker directly, both portfolio/trade domain concepts.
 *
 * `false_breakout_status`/`perfection` are the only fields the caller can
 * set — `weekly_impulse`/`daily_impulse`/`price_vs_value` are always
 * auto-populated server-side from `app.signals.engine.analyse()`'s own
 * output for `ticker` and can't be overridden from here (`TradeApgarIn` has
 * no fields for them at all). There is also no backend endpoint to fetch
 * just those three auto fields on their own — every score call requires the
 * two manual answers too — so this dialog requires one explicit "Score"
 * click (pre-filled with the lowest-scoring `'none'`/`'neither'` defaults)
 * rather than auto-fetching on open; clicking "Re-score" after changing
 * either manual select re-runs the same call with the new answers. See
 * `frontend-trade-apgar`'s `decisions` entry for why this shape was chosen
 * over an auto-fetch-on-open effect.
 */
export default function TradeApgarDialog({ ticker, onClose }: TradeApgarDialogProps) {
  const theme = useTheme()
  const [falseBreakoutStatus, setFalseBreakoutStatus] = useState<FalseBreakoutStatus>('none')
  const [perfection, setPerfection] = useState<Perfection>('neither')
  const scoreTradeApgar = useScoreTradeApgar()

  // Reset local state whenever the dialog switches to a different ticker (or
  // closes), so scoring a second ticker doesn't start pre-filled with the
  // first ticker's manual answers or a stale result/error, same shared
  // pattern FollowUpReviewDialog uses for its own `trade` prop.
  useResetOnSubjectChange(ticker, () => {
    setFalseBreakoutStatus('none')
    setPerfection('neither')
    scoreTradeApgar.reset()
  })

  const handleClose = () => {
    onClose()
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    // The form only mounts while the Dialog is open, which only happens
    // while `ticker !== null` (see the `open` prop below) -- unreachable
    // through the UI in practice, purely so TypeScript narrows `ticker` from
    // `string | null` before it's passed to `mutate` below, same defensive
    // pattern as FollowUpReviewDialog's own `trade` guard.
    /* v8 ignore next 3 */
    if (!ticker) {
      return
    }
    scoreTradeApgar.mutate({ ticker, false_breakout_status: falseBreakoutStatus, perfection })
  }

  const result = scoreTradeApgar.data

  // Guards against MUI's `Dialog` firing its own `onClose` on
  // Escape/backdrop-click mid-score, regardless of the Close button's own
  // `disabled` state -- see `useGuardedDialogClose`'s own doc comment.
  const handleDialogClose = useGuardedDialogClose(handleClose, scoreTradeApgar.isPending)

  return (
    <Dialog open={ticker !== null} onClose={handleDialogClose} fullWidth maxWidth="sm">
      <DialogTitle>Trade Apgar{ticker ? `: ${ticker}` : ''}</DialogTitle>
      <form onSubmit={handleSubmit}>
        <DialogContent>
          <Stack spacing={2}>
            <DialogContentText>
              Elder's pre-trade go/no-go check (ch. 58) — go requires a total score of at least 7
              AND no single question scored 0. Weekly Impulse, daily Impulse, and price vs. value
              are auto-populated from today's analysis; false breakout status and
              &quot;perfection&quot; are your own call.
            </DialogContentText>
            {scoreTradeApgar.isError && <ErrorState error={scoreTradeApgar.error} />}

            <FormControl fullWidth>
              <InputLabel id="trade-apgar-false-breakout-label">False breakout status</InputLabel>
              <Select
                labelId="trade-apgar-false-breakout-label"
                label="False breakout status"
                value={falseBreakoutStatus}
                onChange={(event: SelectChangeEvent) =>
                  setFalseBreakoutStatus(event.target.value as FalseBreakoutStatus)
                }
              >
                {FALSE_BREAKOUT_OPTIONS.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            <FormControl fullWidth>
              <InputLabel id="trade-apgar-perfection-label">&quot;Perfection&quot;</InputLabel>
              <Select
                labelId="trade-apgar-perfection-label"
                label="&quot;Perfection&quot;"
                value={perfection}
                onChange={(event: SelectChangeEvent) =>
                  setPerfection(event.target.value as Perfection)
                }
              >
                {PERFECTION_OPTIONS.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            {result && (
              <Stack spacing={1.5}>
                <DataTable
                  columns={columns}
                  rows={result.questions}
                  getRowKey={(row) => row.key}
                  getRowStyle={(row) =>
                    row.score === 0
                      ? { backgroundColor: theme.palette.riskBreach.background }
                      : undefined
                  }
                  ariaLabel="Trade Apgar questions"
                />
                <Alert severity={result.go ? 'success' : 'error'}>
                  <Typography sx={{ fontWeight: 700 }}>
                    {result.go ? 'GO' : 'NO-GO'} — total score {result.total_score}/10
                  </Typography>
                  {!result.go && result.total_score >= 7 && (
                    <Typography variant="body2">
                      Total score meets the ≥7 threshold, but at least one question scored 0 —
                      Elder's "no single zero" rule still blocks this trade.
                    </Typography>
                  )}
                </Alert>
              </Stack>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose} disabled={scoreTradeApgar.isPending}>
            Close
          </Button>
          <Button type="submit" variant="contained" loading={scoreTradeApgar.isPending}>
            {result ? 'Re-score' : 'Score'}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  )
}
