import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import FormControl from '@mui/material/FormControl'
import FormControlLabel from '@mui/material/FormControlLabel'
import FormLabel from '@mui/material/FormLabel'
import Radio from '@mui/material/Radio'
import RadioGroup, { type RadioGroupProps } from '@mui/material/RadioGroup'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import { useState, type FormEvent } from 'react'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import type { TradingModeOut } from '../../../api/settings'
import { useTradingMode } from '../hooks/useTradingMode'
import { useUpdateTradingMode } from '../hooks/useUpdateTradingMode'

// Mirrors the backend's own canonical interval-code grammar exactly
// (`app.signals.timeframe._CODE_PATTERN`): a positive integer with no
// leading zero, immediately followed by exactly one of 'm'/'d'/'w'. This is
// the one piece of the backend's validation this form duplicates
// client-side (per the checklist's own "client-side format validation
// matching the backend's accepted interval-code pattern" wording) — the
// *ordering* rule (long_term > intermediate > short_term) and the
// factor-of-five spacing guideline are deliberately left to the backend's
// 422/`factor_of_five_warnings` response instead of a second implementation
// here; see this task's `decisions` entry.
const INTERVAL_CODE_PATTERN = /^[1-9][0-9]*[mdw]$/

type TripleLeg = 'long_term' | 'intermediate' | 'short_term'

interface TripleFormState {
  long_term: string
  intermediate: string
  short_term: string
}

type TripleFormErrors = Partial<Record<TripleLeg, string>>

const TRIPLE_LEGS: readonly TripleLeg[] = ['long_term', 'intermediate', 'short_term']

const LEG_LABELS: Record<TripleLeg, string> = {
  long_term: 'Long-term (Tide / Screen 1)',
  intermediate: 'Intermediate (Wave / Screen 2)',
  short_term: 'Short-term (Trigger / Screen 3)',
}

const LEG_PLACEHOLDERS: Record<TripleLeg, string> = {
  long_term: "e.g. '25m'",
  intermediate: "e.g. '5m'",
  short_term: "e.g. '2m'",
}

function emptyTriple(): TripleFormState {
  return { long_term: '', intermediate: '', short_term: '' }
}

function tripleFromResponse(
  triple: TradingModeOut['day_trader_timeframe_triple'],
): TripleFormState {
  if (!triple) {
    return emptyTriple()
  }
  return {
    long_term: triple.long_term,
    intermediate: triple.intermediate,
    short_term: triple.short_term,
  }
}

function validateTriple(mode: TradingModeOut['mode'], triple: TripleFormState): TripleFormErrors {
  if (mode !== 'day_trader') {
    return {}
  }
  const errors: TripleFormErrors = {}
  for (const leg of TRIPLE_LEGS) {
    const value = triple[leg].trim()
    if (!value) {
      errors[leg] = 'Required.'
    } else if (!INTERVAL_CODE_PATTERN.test(value)) {
      errors[leg] =
        "Must be a positive whole number immediately followed by 'm' (minutes), 'd' (days), or 'w' (weeks) -- e.g. '25m'."
    }
  }
  return errors
}

interface TradingModeFieldsProps {
  /** Already-resolved `GET /api/settings/trading-mode` response, used only
   * to compute this component's `useState` initializers at mount -- never
   * re-read after that, so a refetch (e.g. triggered by this same form's
   * own successful submit) never clobbers in-progress edits. */
  initialData: TradingModeOut
}

/**
 * The trading-mode radio group plus (when 'day_trader' is selected) the
 * three timeframe-triple leg fields. Decision (this task's `decisions`
 * entry): each leg is a single free-text field for the whole canonical
 * interval code (e.g. '25m'), not a split count-number-field +
 * unit-dropdown pair -- the wire format (`TimeframeTripleIn.long_term` etc.)
 * is already that one string, so a single field maps to it directly with no
 * join/split step, and the checklist's own wording ("entering the three
 * timeframe-interval codes") already frames this as entering codes, not
 * assembling them from parts.
 */
function TradingModeFields({ initialData }: TradingModeFieldsProps) {
  const [mode, setMode] = useState<TradingModeOut['mode']>(initialData.mode)
  const [triple, setTriple] = useState<TripleFormState>(
    tripleFromResponse(initialData.day_trader_timeframe_triple),
  )
  const [errors, setErrors] = useState<TripleFormErrors>({})
  const updateTradingMode = useUpdateTradingMode()

  // Decision (this task's `decisions` entry): factor-of-five spacing
  // warnings are never recomputed client-side as the user types -- only
  // ever shown as the backend's own last-known verdict, either from the
  // just-submitted response or (before any submission this session) from
  // whatever was already persisted. Recomputing ch. 39's guideline-band
  // ratio in TypeScript would duplicate business logic the backend already
  // owns (`app.signals.timeframe.TimeframeTriple.factor_of_five_warnings`),
  // the same "one place, testable once" principle Frontend.md §5 already
  // applies to indicator math.
  const persistedWarnings = initialData.day_trader_timeframe_triple?.factor_of_five_warnings ?? []
  const submittedWarnings = updateTradingMode.data?.day_trader_timeframe_triple
    ?.factor_of_five_warnings
  const warningsToShow = mode === 'day_trader' ? (submittedWarnings ?? persistedWarnings) : []

  const handleModeChange: RadioGroupProps['onChange'] = (event) => {
    updateTradingMode.reset()
    setMode(event.target.value as TradingModeOut['mode'])
  }

  const handleTripleChange = (leg: TripleLeg) => (event: { target: { value: string } }) => {
    updateTradingMode.reset()
    setTriple((current) => ({ ...current, [leg]: event.target.value }))
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    const validationErrors = validateTriple(mode, triple)
    setErrors(validationErrors)
    if (Object.keys(validationErrors).length > 0) {
      return
    }

    updateTradingMode.mutate(
      mode === 'day_trader'
        ? {
            mode,
            day_trader_timeframe_triple: {
              long_term: triple.long_term.trim(),
              intermediate: triple.intermediate.trim(),
              short_term: triple.short_term.trim(),
            },
          }
        : { mode },
    )
  }

  return (
    <Card>
      <CardContent>
        <form onSubmit={handleSubmit}>
          <Stack spacing={2}>
            {updateTradingMode.isError && <ErrorState error={updateTradingMode.error} />}
            {updateTradingMode.isSuccess && <Alert severity="success">Trading mode saved.</Alert>}
            {warningsToShow.map((warning) => (
              <Alert key={warning} severity="warning">
                {warning}
              </Alert>
            ))}

            <FormControl>
              <FormLabel id="trading-mode-label">Trading Mode</FormLabel>
              <RadioGroup aria-labelledby="trading-mode-label" value={mode} onChange={handleModeChange}>
                <FormControlLabel
                  value="swing"
                  control={<Radio />}
                  label="Swing (weekly / daily)"
                />
                <FormControlLabel
                  value="day_trader"
                  control={<Radio />}
                  label="Day Trader (intraday)"
                />
              </RadioGroup>
            </FormControl>

            {mode === 'day_trader' && (
              <Stack spacing={2}>
                <Typography variant="body2" color="text.secondary">
                  Elder ch. 39&apos;s Factor of Five: pick three timeframes, each roughly five
                  times longer than the next. Each leg is a positive whole number immediately
                  followed by &apos;m&apos; (minutes), &apos;d&apos; (days), or &apos;w&apos;
                  (weeks) -- e.g. &apos;25m&apos;.
                </Typography>
                {TRIPLE_LEGS.map((leg) => (
                  <TextField
                    key={leg}
                    label={LEG_LABELS[leg]}
                    value={triple[leg]}
                    onChange={handleTripleChange(leg)}
                    error={Boolean(errors[leg])}
                    helperText={errors[leg] ?? LEG_PLACEHOLDERS[leg]}
                    fullWidth
                  />
                ))}
              </Stack>
            )}

            <Button
              type="submit"
              variant="contained"
              loading={updateTradingMode.isPending}
              sx={{ alignSelf: 'flex-start' }}
            >
              Save
            </Button>
          </Stack>
        </form>
      </CardContent>
    </Card>
  )
}

/**
 * View/switch the app's global trading mode and, when day-trader mode is
 * selected, configure its timeframe triple
 * (docs/architecture/API.md#get-apisettingstrading-mode--put-apisettingstrading-mode,
 * Elder ch. 39). Feature-specific, not `components/common/`: every piece of
 * this form (the swing/day-trader enum, the timeframe-triple legs) is a
 * domain concept this feature owns, not a generic/reusable control (see
 * this task's `decisions` entry).
 */
export default function TradingModeSettingsForm() {
  const modeQuery = useTradingMode()

  // `isPending` (not `isLoading`) is the check that actually narrows
  // `modeQuery.data` to a defined `TradingModeOut` below -- `isLoading` is a
  // derived convenience flag (`isPending && isFetching`) whose type stays
  // plain `boolean` on TanStack Query's own "pending but not fetching"
  // result variant, so checking it alone doesn't rule that variant's
  // `data: undefined` back out for TypeScript.
  if (modeQuery.isPending) {
    return <LoadingState message="Loading trading mode settings..." />
  }
  if (modeQuery.isError) {
    return <ErrorState error={modeQuery.error} />
  }

  return <TradingModeFields initialData={modeQuery.data} />
}
