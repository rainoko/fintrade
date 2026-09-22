import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import FormControl from '@mui/material/FormControl'
import InputLabel from '@mui/material/InputLabel'
import MenuItem from '@mui/material/MenuItem'
import Select, { type SelectChangeEvent } from '@mui/material/Select'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useState, type FormEvent } from 'react'
import type { ApiError } from '../../../api/client'
import type { DailyHomeworkIn, DailyHomeworkOut } from '../../../api/homework'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import { useDailyHomeworkToday } from '../hooks/useDailyHomeworkToday'
import { useRecordDailyHomework } from '../hooks/useRecordDailyHomework'
import { useYesterdayTradingSuggestion } from '../hooks/useYesterdayTradingSuggestion'
import HomeworkScoreBanner from './HomeworkScoreBanner'

type ScoreKey =
  | 'physical_state_score'
  | 'yesterday_trading_score'
  | 'trade_planning_score'
  | 'mood_score'
  | 'schedule_score'

type Scores = Record<ScoreKey, 0 | 1 | 2>

// The starting point whenever there's no already-recorded entry for today
// and no usable "yesterday" suggestion -- 1 (the neutral middle answer on
// the book's own 0/1/2 scale) is a deliberately unopinionated default
// rather than 0 (which would open the form already showing a "red"/"don't
// trade" band before the user has answered anything) or 2 (overly
// optimistic) -- see this task's `decisions` entry.
const NEUTRAL_SCORES: Scores = {
  physical_state_score: 1,
  yesterday_trading_score: 1,
  trade_planning_score: 1,
  mood_score: 1,
  schedule_score: 1,
}

interface QuestionDef {
  key: ScoreKey
  question: string
  // Labels for answers 0, 1, 2 respectively -- the book's own wording per
  // DailyHomeworkIn's field descriptions (docs/architecture/API.md).
  options: readonly [string, string, string]
}

const QUESTIONS: readonly QuestionDef[] = [
  {
    key: 'physical_state_score',
    question: 'How do I feel physically?',
    options: ['Poor', 'Okay', 'Good'],
  },
  {
    key: 'yesterday_trading_score',
    question: 'How did I trade yesterday?',
    options: ['Poorly', 'Neutral / no trades', 'Well'],
  },
  {
    key: 'trade_planning_score',
    question: 'Have I done my trade planning?',
    options: ['No', 'Partially', 'Fully'],
  },
  {
    key: 'mood_score',
    question: 'What is my mood?',
    options: ['Poor', 'Neutral', 'Good'],
  },
  {
    key: 'schedule_score',
    question: 'How busy is my schedule today?',
    options: ['Very busy', 'Somewhat busy', 'Clear'],
  },
]

function scoresFromEntry(entry: DailyHomeworkOut): Scores {
  return {
    physical_state_score: entry.physical_state_score as 0 | 1 | 2,
    yesterday_trading_score: entry.yesterday_trading_score as 0 | 1 | 2,
    trade_planning_score: entry.trade_planning_score as 0 | 1 | 2,
    mood_score: entry.mood_score as 0 | 1 | 2,
    schedule_score: entry.schedule_score as 0 | 1 | 2,
  }
}

interface HomeworkQuestionsFormProps {
  /** Computed once by the parent from already-loaded query data (see
   * DailyHomeworkForm below) -- never recomputed after this component
   * mounts, so (aside from `yesterday_trading_score`'s suggestion-driven
   * render-time adjustment below) it's plain initial React state, not
   * something that needs to be kept in sync after the fact. */
  initialScores: Scores
  /** Today's already-recorded entry, if any, to show a score band for
   * before the user has (re-)submitted anything this session. */
  initialResult: DailyHomeworkOut | null
  /**
   * The yesterday-trading-suggestion's resolved score, or `null` while it's
   * still pending, has failed, has no usable score, or is inapplicable
   * (`initialResult` already exists). Deliberately a live prop rather than
   * folded into `initialScores`: the suggestion query only starts once
   * `DailyHomeworkForm` knows there's no existing entry for today (see this
   * task's `decisions` entry), so on a genuinely new entry it hasn't even
   * started fetching -- let alone resolved -- by the time this component
   * first mounts. A `useState` initializer can only capture a value that
   * already exists at mount time, so prefilling from one that arrives later
   * needs the render-time adjustment below instead.
   */
  suggestedScore: 0 | 1 | 2 | null
  onSubmit: (scores: DailyHomeworkIn) => void
  isSubmitting: boolean
  submitError: ApiError | null
  /** The just-submitted result, if a submission has succeeded this session
   * -- takes priority over `initialResult` since it may differ (this is an
   * overwrite of the same day's entry). */
  lastResult: DailyHomeworkOut | null
}

function HomeworkQuestionsForm({
  initialScores,
  initialResult,
  suggestedScore,
  onSubmit,
  isSubmitting,
  submitError,
  lastResult,
}: HomeworkQuestionsFormProps) {
  const [scores, setScores] = useState<Scores>(initialScores)
  // Whether the user has changed `yesterday_trading_score` themselves -- so
  // the render-time adjustment below never overwrites their answer once a
  // (necessarily later-arriving) suggestion resolves. Plain `useState`, not
  // a ref: the render-time adjustment pattern below reads this value during
  // render, and React (and this codebase's own lint config, via
  // `react-hooks/refs`) disallows reading a ref's `current` during render --
  // only in effects/handlers, neither of which this needs.
  const [hasEditedYesterdayScore, setHasEditedYesterdayScore] = useState(false)
  // Tracks the last `suggestedScore` this component has already reacted to,
  // so the adjustment below only fires once per actual change, the same
  // guarded pattern `useResetOnSubjectChange`/`AddPositionDialog` use for
  // "adjust state when a prop changes" (React's own documented alternative
  // to a `useEffect` for this: https://react.dev/learn/you-might-not-need-an-effect,
  // also avoids the lint-enforced `react-hooks/set-state-in-effect` rule).
  const [prevSuggestedScore, setPrevSuggestedScore] = useState(suggestedScore)

  // Prefills `yesterday_trading_score` once the suggestion resolves, for a
  // genuinely new entry only. Deliberately done during render rather than in
  // a `useState` initializer or a `useEffect`: unlike the other four
  // questions' neutral defaults (available synchronously at mount), the
  // suggestion is gated on today's entry query already having resolved with
  // no existing entry (see `DailyHomeworkForm`), so on a cold load it hasn't
  // started fetching -- let alone resolved -- by the time this component
  // first mounts; an initializer can only ever capture what's known at that
  // first mount. Adjusting state during render (rather than in an effect)
  // means the prefilled value lands in the very same render `suggestedScore`
  // changes in, with no extra committed frame showing the stale value first.
  if (suggestedScore !== prevSuggestedScore) {
    setPrevSuggestedScore(suggestedScore)
    // An existing entry's own recorded answer always wins -- never
    // overwritten by a same-day suggestion recomputed after the fact (the
    // parent also never enables the suggestion query in this case, but the
    // check stays here too since this adjustment owns the write to
    // `scores`).
    if (!initialResult && !hasEditedYesterdayScore && suggestedScore !== null) {
      setScores((current) => ({ ...current, yesterday_trading_score: suggestedScore }))
    }
  }

  const handleChange = (key: ScoreKey) => (event: SelectChangeEvent) => {
    if (key === 'yesterday_trading_score') {
      setHasEditedYesterdayScore(true)
    }
    const value = Number(event.target.value) as 0 | 1 | 2
    setScores((current) => ({ ...current, [key]: value }))
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    onSubmit(scores)
  }

  const result = lastResult ?? initialResult

  return (
    <Card>
      <CardContent>
        <form onSubmit={handleSubmit}>
          <Stack spacing={2}>
            <Typography variant="h6" component="h2">
              Am I ready to trade today?
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Elder&apos;s ch. 57 daily psychological readiness self-test — answer honestly,
              every day, before you start trading.
            </Typography>

            {submitError && <ErrorState error={submitError} />}

            {QUESTIONS.map((questionDef) => (
              <FormControl fullWidth key={questionDef.key}>
                <InputLabel id={`homework-${questionDef.key}-label`}>
                  {questionDef.question}
                </InputLabel>
                <Select
                  labelId={`homework-${questionDef.key}-label`}
                  label={questionDef.question}
                  value={String(scores[questionDef.key])}
                  onChange={handleChange(questionDef.key)}
                >
                  {questionDef.options.map((label, value) => (
                    <MenuItem key={value} value={String(value)}>
                      {value} — {label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            ))}

            {result && <HomeworkScoreBanner totalScore={result.total_score} band={result.band} />}

            <Button
              type="submit"
              variant="contained"
              loading={isSubmitting}
              sx={{ alignSelf: 'flex-start' }}
            >
              {result ? 'Update' : 'Save'}
            </Button>
          </Stack>
        </form>
      </CardContent>
    </Card>
  )
}

/**
 * Elder ch. 57's "Am I ready to trade?" 5-question daily psychological
 * readiness self-test form (docs/ideas.md's ch. 57 entry,
 * docs/architecture/API.md's `POST /api/daily-homework`). One question per
 * row, each answered on the book's own 0/1/2 scale; submitting (or loading
 * an already-recorded day) shows the summed score's color-coded band via
 * `HomeworkScoreBanner`.
 *
 * This component only loads/error-handles the query feeding the form's
 * *initial* state that's actually essential (`useDailyHomeworkToday`) and
 * hands a plain, already-resolved `initialScores` to the child
 * `HomeworkQuestionsForm` for four of the five questions, as plain `useState`
 * initial state that's never adjusted after mount. The fifth question,
 * `yesterday_trading_score`'s suggestion-driven prefill, is the one
 * exception -- see `HomeworkQuestionsForm`'s own `suggestedScore` prop doc
 * and its render-time state adjustment for why that one genuinely can't be
 * captured by a `useState` initializer here, and this task's `decisions`
 * entry for why an earlier attempt at avoiding that restructure entirely (an
 * `enabled: !existingEntry`-only gate) fell short.
 *
 * The form's render gate only waits on `useDailyHomeworkToday`, *not* on
 * `useYesterdayTradingSuggestion` (see the parent task's `decisions` entry,
 * frontend-daily-homework-page-followups): the suggestion feeds exactly one
 * optional default (`yesterday_trading_score`'s pre-fill when there's no
 * already-recorded entry for today), so it's never worth delaying the other
 * four questions' render on. The suggestion query only starts once
 * `useDailyHomeworkToday` has resolved *and* revealed there's no existing
 * entry (`enabled: todayQuery.isSuccess && !existingEntry`, below) -- unlike
 * a bare `!existingEntry` gate (which is `true` from the very first render,
 * since `existingEntry` is `null`/falsy for as long as `todayQuery` hasn't
 * settled), this never dispatches the request at all when today's entry
 * turns out to already exist, on a cold load or otherwise (see this task's
 * `decisions` entry for why the bare gate alone wasn't sufficient). The
 * tradeoff: on a genuinely new entry, the suggestion fetch can no longer
 * start until *after* `HomeworkQuestionsForm` has already mounted with the
 * neutral default, so its prefill (when one arrives) necessarily lands via
 * `HomeworkQuestionsForm`'s render-time state adjustment, not synchronously
 * at mount.
 *
 * Pre-fill behavior (see this task's `decisions` entry): if today's entry
 * is already recorded, the form loads with those exact answers
 * (re-submitting overwrites, per the endpoint's own upsert semantics).
 * Otherwise every question defaults to the neutral middle answer
 * (`NEUTRAL_SCORES`) -- except `yesterday_trading_score`, which is swapped
 * in-place for `useYesterdayTradingSuggestion`'s suggested value once it
 * settles successfully with one (via `HomeworkQuestionsForm`'s render-time
 * state adjustment), since that endpoint exists specifically so most days
 * require no manual recall for that one question, unless the user has already changed that
 * field themselves by the time it arrives. A failure (or a still-pending,
 * or a null-result) suggestion is treated as "no suggestion available"
 * (stays at the neutral default) rather than blocking the form -- it's a
 * pure UX enhancement, not essential data, unlike today's own entry (whose
 * load failure does block, since submitting without knowing whether today
 * already has a recorded entry could silently produce a wrong
 * "Save"/"Update" experience).
 */
export default function DailyHomeworkForm() {
  const todayQuery = useDailyHomeworkToday()
  const existingEntry = todayQuery.data?.entry ?? null
  // Gated on `todayQuery.isSuccess && !existingEntry`, not a bare
  // `!existingEntry`: `existingEntry` alone is `null` (falsy) for as long as
  // `todayQuery` hasn't settled yet, so a bare `!existingEntry` gate is
  // `true` from the very first render regardless of the eventual outcome --
  // it never actually prevents the fetch on a cold load whose entry turns
  // out to already exist (see this task's `decisions` entry: an earlier
  // attempt at exactly that bare gate was reopened by review for this
  // reason, confirmed via a live browser walkthrough). Requiring
  // `todayQuery.isSuccess` first means this query is never enabled at all
  // across a cold load's existing-entry case -- it only ever turns `true`
  // once `todayQuery` has resolved and revealed there's no existing entry,
  // at which point it stays `true` (existingEntry can't retroactively
  // become truthy once `todayQuery` has already settled with `null`).
  const suggestionQuery = useYesterdayTradingSuggestion({
    enabled: todayQuery.isSuccess && !existingEntry,
  })
  const recordHomework = useRecordDailyHomework()

  if (todayQuery.isLoading) {
    return <LoadingState message="Loading today's self-test..." />
  }
  if (todayQuery.isError) {
    return <ErrorState error={todayQuery.error} />
  }

  // Only meaningful when there's no existing entry -- the only case the
  // query above is ever enabled for. `null` while it's still pending, has
  // failed, or has no usable score to suggest; all three are treated
  // identically as "no suggestion available" by `HomeworkQuestionsForm`'s
  // render-time state adjustment.
  const suggestedScore: 0 | 1 | 2 | null =
    !existingEntry && suggestionQuery.isSuccess
      ? ((suggestionQuery.data.suggested_score ?? null) as 0 | 1 | 2 | null)
      : null
  const initialScores: Scores = existingEntry ? scoresFromEntry(existingEntry) : NEUTRAL_SCORES

  return (
    <HomeworkQuestionsForm
      initialScores={initialScores}
      initialResult={existingEntry}
      suggestedScore={suggestedScore}
      onSubmit={(scores) => recordHomework.mutate(scores)}
      isSubmitting={recordHomework.isPending}
      submitError={recordHomework.isError ? recordHomework.error : null}
      lastResult={recordHomework.data ?? null}
    />
  )
}
