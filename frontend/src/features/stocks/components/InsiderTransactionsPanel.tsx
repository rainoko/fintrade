import Alert from '@mui/material/Alert'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import type {
  ExtendedDataOut,
  InsiderClusterOut,
  InsiderTransactionOut,
} from '../../../api/stocks'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import {
  formatDate,
  formatNullableCurrency,
  formatNullableNumber,
} from '../../../utils/format'
import { sortClustersByRecentWindowEnd } from '../../../utils/insiderClusters'
import {
  insiderClustersHelp,
  insiderTransactionsHelp,
  insiderTransactionsUnavailableHelp,
} from './metricHelpContent'

export interface InsiderTransactionsPanelProps {
  /**
   * `AnalysisResponse.extended_data` -- see `FundamentalDataPanelProps`'s
   * own doc comment for why this is a genuinely non-optional, non-nullable
   * type (matches `backend/app/api/schemas.py` exactly). Only
   * `insider_transactions` and `unavailable_reason` are read from it here;
   * the rest (earnings/dividend dates, short interest) is
   * `FundamentalDataPanel`'s concern.
   */
  extendedData: ExtendedDataOut
  /**
   * `AnalysisResponse.insider_clusters` -- a top-level field SIBLING to
   * `extended_data` (not nested inside it, per
   * backend-insider-transaction-clusters's own `decisions` entry), so it's
   * its own prop here rather than destructured out of `extendedData`.
   * Typed nullable/optional for the same reason `extendedData` above is:
   * several of `StockDetailPage.test.tsx`'s existing hand-rolled partial
   * `AnalysisResponse` fixtures (predating this field) omit it entirely,
   * leaving it `undefined` at runtime even though a real backend response
   * always supplies it as a (possibly empty) array.
   */
  insiderClusters: InsiderClusterOut[] | null | undefined
}

interface InsiderRow extends InsiderTransactionOut {
  _key: string
}

interface InsiderClusterCalloutsProps {
  clusters: readonly InsiderClusterOut[]
  /** Whether the raw insider-transactions table (above/below this block) has any rows at all -- see this component's own doc comment for why this gates the "no cluster detected" note. */
  hasTransactions: boolean
}

/**
 * Renders every currently-detected cluster (not just the most recent one --
 * see this task's `decisions` entry for why the full, unbounded
 * `insider_clusters` array is shown rather than truncated), most recent
 * (`window_end_date`) first. Each cluster is its own compact `info`-severity
 * callout naming direction, distinct-insider count, filing count, and the
 * window's date range -- deliberately `severity="info"`, and a plain MUI
 * `Chip` colored via `color="success"/"error"` rather than
 * `theme.palette.signal.buy/sell`, so a cluster callout never visually reads
 * as this app's own BUY/SELL Triple Screen signal (`common/SignalBadge`
 * reuses that exact palette for that exact purpose) -- clusters are purely
 * informational context, never a signal input (see
 * backend-insider-transaction-clusters's own `decisions` entry), the same
 * distinction this panel's own earnings-warning-banner `decisions` entry
 * already drew between a plain `Alert` and `common/RiskBreachBanner`.
 *
 * When there are no qualifying clusters -- the common case, per this task's
 * own description -- shows a quiet one-line note rather than either
 * complete silence or a loud empty-state card, but ONLY when there's at
 * least one raw insider transaction to say "none of these filings formed a
 * cluster" about; when the raw table itself is empty, the table's own
 * "No insider transactions currently reported" empty message already says
 * everything there is to say, and a second empty-cluster note under it
 * would be redundant noise, not additional explanation.
 */
function InsiderClusterCallouts({
  clusters,
  hasTransactions,
}: InsiderClusterCalloutsProps) {
  if (clusters.length === 0) {
    if (!hasTransactions) {
      return null
    }
    return (
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ display: 'block', mb: 1.5 }}
        data-testid="insider-cluster-empty-note"
      >
        No insider-transaction cluster currently detected among these filings (3+ distinct
        insiders trading the same direction within a rolling 30-day window).
      </Typography>
    )
  }

  const sortedClusters = sortClustersByRecentWindowEnd(clusters)

  return (
    <Stack spacing={1} sx={{ mb: 1.5 }}>
      {sortedClusters.map((cluster, index) => {
        const sharesClause =
          cluster.total_shares !== null
            ? `, ${formatNullableNumber(cluster.total_shares)} shares`
            : ''
        const valueClause =
          cluster.total_value !== null
            ? `, ${formatNullableCurrency(cluster.total_value)}`
            : ''
        return (
          <Alert
            key={`${cluster.direction}-${cluster.window_start_date}-${cluster.window_end_date}-${index}`}
            severity="info"
            icon={false}
            data-testid="insider-cluster-callout"
          >
            <Stack
              direction="row"
              spacing={1}
              sx={{ alignItems: 'center', flexWrap: 'wrap' }}
            >
              <Chip
                label={cluster.direction === 'buy' ? 'BUY CLUSTER' : 'SELL CLUSTER'}
                size="small"
                color={cluster.direction === 'buy' ? 'success' : 'error'}
                sx={{ fontWeight: 700 }}
              />
              <Typography variant="body2">
                {/* `transaction_count` is never singular -- see
                    `insiderClustersHelp`'s own comment on the equivalent
                    text for why a "1 filing" case can't occur for real
                    cluster data. */}
                {cluster.insiders.length} distinct insiders ({cluster.insiders.join(', ')}
                ) -- {cluster.transaction_count} filings between{' '}
                {formatDate(cluster.window_start_date)} and{' '}
                {formatDate(cluster.window_end_date)}
                {sharesClause}
                {valueClause}.
              </Typography>
            </Stack>
          </Alert>
        )
      })}
    </Stack>
  )
}

const insiderColumns: DataTableColumn<InsiderRow>[] = [
  {
    key: 'start_date',
    header: 'Date',
    sortable: true,
    render: (row) => (row.start_date ? formatDate(row.start_date) : '—'),
  },
  { key: 'insider', header: 'Insider', render: (row) => row.insider ?? '—' },
  { key: 'position', header: 'Position', render: (row) => row.position ?? '—' },
  {
    key: 'shares',
    header: 'Shares',
    align: 'right',
    sortable: true,
    render: (row) => formatNullableNumber(row.shares),
  },
  {
    key: 'value',
    header: 'Value',
    align: 'right',
    sortable: true,
    render: (row) => formatNullableCurrency(row.value),
  },
  { key: 'transaction_text', header: 'Transaction' },
]

/**
 * Recent insider transactions (`AnalysisResponse.insider_transactions`) and
 * detected insider-transaction clusters (`AnalysisResponse.insider_clusters`,
 * backend-insider-transaction-clusters) for the current ticker -- purely
 * informational context never read by signal/confidence computation (same
 * as `FundamentalDataPanel`, which this component used to be the last `Card`
 * inside). Feature component (not `common/`): every field here is a
 * ticker-specific concept tied directly to `AnalysisResponse`.
 *
 * Extracted out of `FundamentalDataPanel` and rendered by `StockDetailPage`
 * as the LAST block on the page, after `StockCharts`
 * (frontend-stock-detail-insider-transactions-last) -- see that task's
 * `decisions` entry for why: `FundamentalDataPanel`'s own top-of-page
 * placement is motivated specifically by its earnings-date warning banner
 * (ch. 58's "a nasty surprise can jump straight past any stop"), not by
 * Insider Transactions, which was simply the last thing rendered inside that
 * panel as an implementation detail of how it happened to be composed.
 * Insider transactions are Elder ch. 37's own "secondary, worth noting, not
 * urgent" signal -- there's no equivalent time-pressure reason for this
 * block to compete for top-of-page attention with the earnings banner, so
 * moving it to the bottom doesn't lose anything that placement protected.
 *
 * `insider_clusters` is rendered as a set of compact callouts
 * (`InsiderClusterCallouts` below) directly above the raw
 * insider-transactions table, inside the same "Insider Transactions" card --
 * both describe the same underlying filing history, one raw and one
 * clustered, so they stay visually grouped together rather than becoming
 * two unrelated-looking cards (frontend-insider-clusters-badge's own
 * `decisions` entry) -- a rationale this move doesn't disturb, since both
 * move together as one unit.
 *
 * Handles `extendedData.unavailable_reason === 'fallback_provider_active'`
 * with its own explicit, visually distinct empty state (a dashed-border
 * card naming the cause, mirroring `FundamentalDataPanel`'s own
 * equivalent branch) rather than letting that messaging silently disappear
 * now that insider transactions are no longer inside the same early-return
 * branch as earnings/dividend/short-interest (this task's own `decisions`
 * entry, resolving the edge case its own description called out).
 */
export default function InsiderTransactionsPanel({
  extendedData,
  insiderClusters,
}: InsiderTransactionsPanelProps) {
  if (extendedData.unavailable_reason === 'fallback_provider_active') {
    return (
      <Card variant="outlined" sx={{ borderStyle: 'dashed', borderColor: 'divider' }}>
        <CardContent>
          <Stack
            direction="row"
            spacing={1}
            sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1 }}
          >
            <Stack spacing={0}>
              <Typography variant="subtitle2">Insider Transactions</Typography>
              <Typography variant="caption" color="text.secondary">
                Unavailable -- fallback provider active
              </Typography>
            </Stack>
            <MetricHelp
              metricLabel={insiderTransactionsUnavailableHelp.metricLabel}
              definition={insiderTransactionsUnavailableHelp.definition}
              elderContext={insiderTransactionsUnavailableHelp.elderContext}
              valueInterpretation={insiderTransactionsUnavailableHelp.interpretValue()}
            />
          </Stack>
          <Typography variant="body2" color="text.secondary">
            Insider transactions aren’t available for this ticker right now -- the
            fallback (Stooq) market data provider is currently serving this ticker and has
            no equivalent for this data. This is distinct from “checked, nothing found.”
          </Typography>
        </CardContent>
      </Card>
    )
  }

  const { insider_transactions: insiderTransactions } = extendedData

  const insiderRows: InsiderRow[] = insiderTransactions.map((transaction, index) => ({
    ...transaction,
    _key: `${index}-${transaction.insider ?? 'unknown'}-${transaction.start_date ?? 'no-date'}`,
  }))

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack
          direction="row"
          spacing={1}
          sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1 }}
        >
          <Typography variant="subtitle2">Insider Transactions</Typography>
          <MetricHelp
            metricLabel={insiderTransactionsHelp.metricLabel}
            definition={insiderTransactionsHelp.definition}
            elderContext={insiderTransactionsHelp.elderContext}
            valueInterpretation={insiderTransactionsHelp.interpretValue(
              insiderTransactions,
            )}
          />
        </Stack>

        <Stack
          direction="row"
          spacing={1}
          sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1 }}
        >
          <Typography variant="caption" sx={{ fontWeight: 700 }} color="text.secondary">
            Detected Clusters
          </Typography>
          <MetricHelp
            metricLabel={insiderClustersHelp.metricLabel}
            definition={insiderClustersHelp.definition}
            elderContext={insiderClustersHelp.elderContext}
            valueInterpretation={insiderClustersHelp.interpretValue(insiderClusters ?? [])}
          />
        </Stack>
        <InsiderClusterCallouts
          clusters={insiderClusters ?? []}
          hasTransactions={insiderTransactions.length > 0}
        />

        <DataTable
          columns={insiderColumns}
          rows={insiderRows}
          getRowKey={(row) => row._key}
          emptyMessage="No insider transactions currently reported for this ticker."
          ariaLabel="Insider transactions"
        />
      </CardContent>
    </Card>
  )
}
