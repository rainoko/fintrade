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
   * mounts, so it's plain initial React state, not something an effect
   * needs to keep in sync. */
  initialScores: Scores
  /** Today's already-recorded entry, if any, to show a score band for
   * before the user has (re-)submitted anything this session. */
  initialResult: DailyHomeworkOut | null
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
  onSubmit,
  isSubmitting,
  submitError,
  lastResult,
}: HomeworkQuestionsFormProps) {
  const [scores, setScores] = useState<Scores>(initialScores)

  const handleChange = (key: ScoreKey) => (event: SelectChangeEvent) => {
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
 * This component only loads/error-handles the two queries feeding the
 * form's *initial* state (`useDailyHomeworkToday`, `useYesterdayTradingSuggestion`)
 * and hands a plain, already-resolved `initialScores` to the child
 * `HomeworkQuestionsForm`, which owns the rest of the form's interactive
 * state locally -- deliberately not a `useEffect` that re-seeds local state
 * from the query results after mount (React's own guidance against using
 * an Effect to adjust state from data that's already available during
 * render -- see this task's `decisions` entry). Waiting for both queries
 * before rendering the interactive form is a small, one-time load (both are
 * fast, local-only endpoints) traded for a form whose initial values are
 * always correct on the very first render, with no seed-after-mount effect
 * or its associated re-render.
 *
 * Pre-fill behavior (see this task's `decisions` entry): if today's entry
 * is already recorded, the form loads with those exact answers
 * (re-submitting overwrites, per the endpoint's own upsert semantics).
 * Otherwise every question defaults to the neutral middle answer
 * (`NEUTRAL_SCORES`) -- except `yesterday_trading_score`, which defaults
 * instead to `useYesterdayTradingSuggestion`'s suggested value when one is
 * available, since that endpoint exists specifically so most days require
 * no manual recall for that one question. A failure loading the suggestion
 * is treated as "no suggestion available" (falls back to the neutral
 * default) rather than blocking the form -- it's a pure UX enhancement, not
 * essential data, unlike today's own entry (whose load failure does block,
 * since submitting without knowing whether today already has a recorded
 * entry could silently produce a wrong "Save"/"Update" experience).
 */
export default function DailyHomeworkForm() {
  const todayQuery = useDailyHomeworkToday()
  const suggestionQuery = useYesterdayTradingSuggestion()
  const recordHomework = useRecordDailyHomework()

  if (todayQuery.isLoading || suggestionQuery.isLoading) {
    return <LoadingState message="Loading today's self-test..." />
  }
  if (todayQuery.isError) {
    return <ErrorState error={todayQuery.error} />
  }

  const existingEntry = todayQuery.data?.entry ?? null
  const suggestedScore = suggestionQuery.data?.suggested_score ?? null
  const initialScores: Scores = existingEntry
    ? scoresFromEntry(existingEntry)
    : {
        ...NEUTRAL_SCORES,
        yesterday_trading_score: (suggestedScore ??
          NEUTRAL_SCORES.yesterday_trading_score) as 0 | 1 | 2,
      }

  return (
    <HomeworkQuestionsForm
      initialScores={initialScores}
      initialResult={existingEntry}
      onSubmit={(scores) => recordHomework.mutate(scores)}
      isSubmitting={recordHomework.isPending}
      submitError={recordHomework.isError ? recordHomework.error : null}
      lastResult={recordHomework.data ?? null}
    />
  )
}
