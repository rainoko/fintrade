import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import type { CFTCCOTMarketOut } from '../../../api/cftc'
import DataTable, { type DataTableColumn } from '../../../components/common/DataTable/DataTable'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import LoadingState from '../../../components/common/LoadingState/LoadingState'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import { formatDate, formatNullableNumber } from '../../../utils/format'
import { useCftcCot } from '../hooks/useCftcCot'
import { cftcCotHelp } from './cftcCotHelp'

/**
 * One group's (commercial / large speculator / small speculator) net
 * position plus its 52-week COT Index, stacked in a single cell -- net and
 * index are always read together per Elder's ch. 37 framing ("read current
 * positioning against historical norms", not the raw net alone), so a
 * single combined cell reads more directly than two separate same-group
 * columns four groups apart in the table.
 */
function GroupCell({
  net,
  cotIndex52w,
}: {
  net: number
  // `CFTCCOTMarketOut`'s `*_cot_index_52w` fields are an optional-and-nullable
  // Pydantic field (`float | None = None`), which `openapi-typescript` renders
  // as `number | null | undefined` -- `undefined` and `null` are both the same
  // "not computable" case here (`formatNullableNumber` already treats them
  // identically), so this is accepted rather than narrowed to `number | null`.
  cotIndex52w: number | null | undefined
}) {
  return (
    <Stack spacing={0}>
      <Typography variant="body2">{formatNullableNumber(net)}</Typography>
      <Typography variant="caption" color="text.secondary">
        COT Index: {formatNullableNumber(cotIndex52w, { maximumFractionDigits: 0 })}
      </Typography>
    </Stack>
  )
}

const COLUMNS: DataTableColumn<CFTCCOTMarketOut>[] = [
  { key: 'display_name', header: 'Market', sortable: true },
  {
    key: 'report_date',
    header: 'Report Date',
    sortable: true,
    render: (row) => formatDate(row.report_date),
  },
  {
    key: 'commercial_net',
    header: 'Commercial (net)',
    align: 'right',
    render: (row) => <GroupCell net={row.commercial_net} cotIndex52w={row.commercial_cot_index_52w} />,
  },
  {
    key: 'large_speculator_net',
    header: 'Large Speculators (net)',
    align: 'right',
    render: (row) => (
      <GroupCell net={row.large_speculator_net} cotIndex52w={row.large_speculator_cot_index_52w} />
    ),
  },
  {
    key: 'small_speculator_net',
    header: 'Small Speculators (net)',
    align: 'right',
    render: (row) => (
      <GroupCell net={row.small_speculator_net} cotIndex52w={row.small_speculator_cot_index_52w} />
    ),
  },
]

/**
 * Watchlist-page widget surfacing `GET /api/cftc/cot`
 * (docs/architecture/API.md#get-apicftccot, docs/ideas.md's ch. 37 entry,
 * frontend-cftc-cot-display) -- a plain table of this app's fixed 5 major
 * futures markets (Euro, Yen, Oil, Gold, Bonds), each row showing the
 * commercial/large-speculator/small-speculator net position plus its own
 * 52-week Williams COT Index (null-safe -- rendered "--" via
 * `formatNullableNumber` when `weeks_of_history` < 2 or the trailing window
 * has zero range, per `CFTCCOTMarketOut`'s own schema doc).
 *
 * A plain `DataTable`, not a chart: see this task's `decisions` entry for
 * the full reasoning -- 5 fixed rows is not a time series (there's nothing
 * to plot a trend *of* across markets), and the per-group net+index detail
 * a user actually wants ("where does commercial positioning sit right now,
 * for which market") is exactly the kind of structured, scannable detail a
 * table preserves and a chart would discard, the same call
 * `DailyHomeworkHistoryTable` made for its own low-cardinality,
 * detail-dense data.
 *
 * Feature component (not `common/`): every field it renders (a futures
 * market, a commercial/speculator net position, a COT Index) is a CFTC/Elder
 * ch. 37 domain concept, and it owns its own `useCftcCot` fetch/loading/
 * error handling so `WatchlistPage` stays a thin composition (Frontend.md
 * §3) -- same reasoning as `MarketBreadthCard`/`PersonalBreadthCard`. Lives
 * under its own `features/cftc/` (not `features/watchlist/`) since every
 * value it renders and the hook backing it are CFTC-domain concepts, not
 * watchlist ones -- mirroring `MarketBreadthCard`'s identical placement
 * under `features/ibkr/` despite also only being rendered from
 * `WatchlistPage`.
 */
export default function CftcCotCard() {
  const cotQuery = useCftcCot()

  if (!cotQuery.data) {
    if (cotQuery.isError) {
      return <ErrorState error={cotQuery.error} />
    }
    return <LoadingState message="Loading CFTC Commitments of Traders data..." />
  }

  const data = cotQuery.data
  const help = cftcCotHelp(data)

  return (
    <Stack spacing={1}>
      <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
        <Typography variant="h6" component="h2">
          Commitments of Traders (CFTC)
        </Typography>
        <MetricHelp
          metricLabel={help.metricLabel}
          definition={help.definition}
          elderContext={help.elderContext}
          valueInterpretation={help.valueInterpretation}
        />
      </Stack>

      <DataTable
        columns={COLUMNS}
        rows={data.markets}
        getRowKey={(row) => row.market_key}
        emptyMessage="No CFTC Commitments of Traders data available."
        ariaLabel="CFTC Commitments of Traders"
      />
      <Typography variant="caption" color="text.secondary">
        COT Index reads &quot;—&quot; when fewer than 2 weeks of CFTC history are available for
        that market/group.
      </Typography>
    </Stack>
  )
}
