import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import PageHeader from '../components/common/PageHeader/PageHeader'
import DailyHomeworkForm from '../features/homework/components/DailyHomeworkForm'

/**
 * "Daily Homework" (`/homework`, `frontend-daily-homework-page`) — Elder
 * ch. 57's "Am I ready to trade?" 5-question psychological readiness
 * self-test, backed by `backend-daily-homework-self-test`. A standalone
 * nav destination (see this task's `decisions` entry for why, over folding
 * it into the Dashboard). Stays thin per Frontend.md §3: all fetching and
 * business logic live in `features/homework/`.
 */
export default function DailyHomeworkPage() {
  return (
    <>
      <PageHeader title="Daily Homework" />
      <Stack spacing={3}>
        <Typography variant="body1" color="text.secondary">
          A short daily check-in before you start trading — this is purely a subjective
          self-assessment, not derived from market data. Scoped to the 5-question
          psychological readiness self-test only (docs/ideas.md&apos;s ch. 57 entry); the
          broader market-context homework spreadsheet from the same chapter is a separate,
          larger idea.
        </Typography>
        <DailyHomeworkForm />
      </Stack>
    </>
  )
}
