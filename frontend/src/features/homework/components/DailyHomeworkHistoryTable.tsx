import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import type { DailyHomeworkOut } from '../../../api/homework'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import { formatDate } from '../../../utils/format'
import { useDailyHomeworkHistory } from '../hooks/useDailyHomeworkHistory'
import { isTooPerfectBand, SEVERITY_BY_BAND } from './band'

/**
 * A plain table (date, the 5 component scores, total_score, band) rather
 * than a trend chart -- see this task's `decisions` entry
 * (frontend-daily-homework-history) for the full reasoning: this self-test
 * is answered at most once a day, so the series is low-cardinality by
 * nature (nothing like a price/indicator history with hundreds of bars),
 * and the per-question breakdown (which of the 5 answers actually drove a
 * low/high day) is exactly the kind of detail a single `total_score` line
 * would discard -- the most useful "trend" information here is still most
 * legible as rows a person reads top-to-bottom, not a plotted line.
 *
 * The `band` column's `Chip` colors reuse the exact same `SEVERITY_BY_BAND`
 * map (and `isTooPerfectBand` predicate for the 9-10 "yellow" case's
 * distinct label) that `HomeworkScoreBanner` itself uses -- both now import
 * them from the shared `./band` module -- rather than inventing a second
 * red/yellow/green scheme, per this task's checklist item.
 */
function BandChip({ totalScore, band }: Pick<DailyHomeworkOut, 'band'> & { totalScore: number }) {
  const label = isTooPerfectBand(totalScore, band) ? `${band} (too perfect)` : band
  return (
    <Chip
      label={label.toUpperCase()}
      color={SEVERITY_BY_BAND[band]}
      size="small"
      sx={{ fontWeight: 700 }}
    />
  )
}

const COMPONENT_SCORE_COLUMNS: DataTableColumn<DailyHomeworkOut>[] = [
  { key: 'physical_state_score', header: 'Physical', align: 'right' },
  { key: 'yesterday_trading_score', header: 'Yesterday', align: 'right' },
  { key: 'trade_planning_score', header: 'Planning', align: 'right' },
  { key: 'mood_score', header: 'Mood', align: 'right' },
  { key: 'schedule_score', header: 'Schedule', align: 'right' },
]

/**
 * History/trend view of past daily self-test entries -- `GET
 * /api/daily-homework` (`operation_id: list_daily_homework`,
 * docs/architecture/API.md), most recent `date` first (the endpoint's own
 * ordering; `sortable` on the `date` column still lets a user flip to
 * oldest-first). Feature component (every column here is a homework
 * self-test domain concept), not `components/common/` -- owns its own
 * `useDailyHomeworkHistory` call so `DailyHomeworkPage` stays a thin
 * composition (Frontend.md §3), same pattern `TradeFollowUpDuePanel`/
 * `TradeJournalPanel` establish for an analogous history table elsewhere in
 * the app.
 */
export default function DailyHomeworkHistoryTable() {
  const historyQuery = useDailyHomeworkHistory()

  const columns: DataTableColumn<DailyHomeworkOut>[] = [
    {
      key: 'date',
      header: 'Date',
      sortable: true,
      render: (row) => formatDate(row.date),
    },
    ...COMPONENT_SCORE_COLUMNS,
    {
      key: 'total_score',
      header: 'Total',
      sortable: true,
      align: 'right',
    },
    {
      key: 'band',
      header: 'Band',
      render: (row) => <BandChip totalScore={row.total_score} band={row.band} />,
    },
  ]

  // Checked in this order (data first) for the same reason
  // TradeFollowUpDuePanel/TradeJournalPanel do: this query has no
  // `enabled: false`/pagination that could leave it settled with neither
  // data nor an error.
  if (!historyQuery.data) {
    if (historyQuery.isError) {
      return <ErrorState error={historyQuery.error} />
    }
    return <LoadingState message="Loading self-test history..." />
  }

  return (
    <Stack spacing={1}>
      <Typography variant="h6" component="h2">
        History
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Every recorded self-test entry, most recent first -- how your &quot;ready to
        trade&quot; score has looked over time.
      </Typography>

      <DataTable
        columns={columns}
        rows={historyQuery.data.items}
        getRowKey={(row) => row.date}
        emptyMessage="No self-test entries recorded yet."
        ariaLabel="Daily homework history"
      />
    </Stack>
  )
}
