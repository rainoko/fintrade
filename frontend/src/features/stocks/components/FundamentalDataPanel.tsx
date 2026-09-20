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
import StatCard from '../../../components/common/StatCard/StatCard'
import {
  formatDate,
  formatNullableCurrency,
  formatNullableNumber,
} from '../../../utils/format'
import { sortClustersByRecentWindowEnd } from '../../../utils/insiderClusters'
import {
  earningsDateHelp,
  exDividendDateHelp,
  fundamentalDataUnavailableHelp,
  insiderClustersHelp,
  insiderTransactionsHelp,
  shortInterestHelp,
} from './metricHelpContent'

export interface FundamentalDataPanelProps {
  /**
   * `AnalysisResponse.extended_data` -- always a present object on a real
   * backend response (`ExtendedDataOut` is a non-optional field per
   * `backend/app/api/schemas.py`), but typed nullable/optional here too:
   * several of this page's own existing tests (`StockDetailPage.test.tsx`'s
   * SELL/HOLD/season/normalize cases) hand-roll a partial `AnalysisResponse`
   * fixture that omits it entirely, the same defensive posture
   * `IndicatorsPanel.tsx`'s `formatValue` already takes toward a generated
   * type it treats as optimistic, not a runtime guarantee.
   */
  extendedData: ExtendedDataOut | null | undefined
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
 * Earnings/dividend dates, short interest, and recent insider transactions
 * for the current ticker (`AnalysisResponse.extended_data`,
 * backend-market-data-extra-fields) -- purely informational context never
 * read by signal/confidence computation (confirmed in that task's own
 * review; every `metricHelpContent.ts` entry this panel uses says so
 * explicitly too). Feature component (not `common/`): every field here is a
 * ticker-specific fundamental-data concept tied directly to `AnalysisResponse`.
 *
 * Placement decision (this task's `decisions` entry): rendered directly
 * below `SignalSummary` on `StockDetailPage`, ahead of `ScreensPanel`/
 * `IndicatorsPanel`/`StockCharts` -- so the earnings-date warning banner
 * below, the highest-value piece per this task's own description ("a nasty
 * earnings surprise can do serious damage to your position... can jump
 * straight past any stop level", Elder ch. 58), is immediately visible near
 * the top of the page rather than buried below several other panels and the
 * price chart.
 *
 * Handles `unavailable_reason === 'fallback_provider_active'` as an
 * explicit, visually distinct state (a dashed-border card naming the cause)
 * rather than silently rendering every field as an unadorned '—' the same
 * way a genuine "checked yfinance, found nothing" null would -- see this
 * task's `decisions` entry for why that distinction matters here.
 *
 * `insiderClusters` (`AnalysisResponse.insider_clusters`,
 * backend-insider-transaction-clusters) is rendered as a set of compact
 * callouts (`InsiderClusterCallouts` below) directly above the raw
 * insider-transactions table, inside the same "Insider Transactions" card
 * -- both describe the same underlying filing history, one raw and one
 * clustered, so they stay visually grouped together rather than becoming
 * two unrelated-looking cards (frontend-insider-clusters-badge's own
 * `decisions` entry). In the `unavailable_reason` branch above, no clusters
 * are shown either -- `insider_clusters` is itself derived from
 * `insider_transactions`, which is empty in that state for the same
 * "not checked while the fallback provider serves this ticker" reason.
 */
export default function FundamentalDataPanel({
  extendedData,
  insiderClusters,
}: FundamentalDataPanelProps) {
  if (!extendedData) {
    return null
  }

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
              <Typography variant="subtitle2">Fundamental Data</Typography>
              <Typography variant="caption" color="text.secondary">
                Unavailable -- fallback provider active
              </Typography>
            </Stack>
            <MetricHelp
              metricLabel={fundamentalDataUnavailableHelp.metricLabel}
              definition={fundamentalDataUnavailableHelp.definition}
              elderContext={fundamentalDataUnavailableHelp.elderContext}
              valueInterpretation={fundamentalDataUnavailableHelp.interpretValue()}
            />
          </Stack>
          <Typography variant="body2" color="text.secondary">
            Earnings/dividend dates, short interest, and insider transactions aren’t
            available for this ticker right now -- the fallback (Stooq) market data
            provider is currently serving this ticker and has no equivalent for this data.
            This is distinct from “checked, nothing found.”
          </Typography>
        </CardContent>
      </Card>
    )
  }

  const {
    earnings_date: earningsDate,
    earnings_within_warning_days: earningsWithinWarningDays,
    ex_dividend_date: exDividendDate,
    shares_short: sharesShort,
    short_ratio: shortRatio,
    short_percent_of_float: shortPercentOfFloat,
    float_shares: floatShares,
    insider_transactions: insiderTransactions,
  } = extendedData

  const insiderRows: InsiderRow[] = insiderTransactions.map((transaction, index) => ({
    ...transaction,
    _key: `${index}-${transaction.insider ?? 'unknown'}-${transaction.start_date ?? 'no-date'}`,
  }))

  return (
    <Stack spacing={2}>
      {earningsWithinWarningDays && (
        <Alert severity="warning" data-testid="earnings-warning-banner">
          <Typography variant="body2" sx={{ fontWeight: 700 }}>
            Earnings expected {earningsDate} -- within the next 14 days. A nasty surprise
            can gap straight through a protective stop; see the Earnings Date help below
            for Elder&rsquo;s own reasoning.
          </Typography>
        </Alert>
      )}

      <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap' }}>
        <StatCard
          label="Earnings Date"
          value={earningsDate ? formatDate(earningsDate) : 'None scheduled'}
          corner={
            <MetricHelp
              metricLabel={earningsDateHelp.metricLabel}
              definition={earningsDateHelp.definition}
              elderContext={earningsDateHelp.elderContext}
              valueInterpretation={earningsDateHelp.interpretValue(
                earningsDate,
                earningsWithinWarningDays,
              )}
            />
          }
        />
        <StatCard
          label="Ex-Dividend Date"
          value={exDividendDate ? formatDate(exDividendDate) : 'None scheduled'}
          corner={
            <MetricHelp
              metricLabel={exDividendDateHelp.metricLabel}
              definition={exDividendDateHelp.definition}
              elderContext={exDividendDateHelp.elderContext}
              valueInterpretation={exDividendDateHelp.interpretValue(exDividendDate)}
            />
          }
        />

        <Card variant="outlined" sx={{ flex: '1 1 260px' }}>
          <CardContent>
            <Stack
              direction="row"
              spacing={1}
              sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1 }}
            >
              <Typography variant="subtitle2">Short Interest</Typography>
              <MetricHelp
                metricLabel={shortInterestHelp.metricLabel}
                definition={shortInterestHelp.definition}
                elderContext={shortInterestHelp.elderContext}
                valueInterpretation={shortInterestHelp.interpretValue(
                  sharesShort,
                  shortRatio,
                  shortPercentOfFloat,
                  floatShares,
                )}
              />
            </Stack>
            <Stack direction="row" spacing={3} sx={{ flexWrap: 'wrap' }}>
              <Stack spacing={0.25}>
                <Typography variant="caption" color="text.secondary">
                  Shares Short
                </Typography>
                <Typography variant="body2">
                  {formatNullableNumber(sharesShort)}
                </Typography>
              </Stack>
              <Stack spacing={0.25}>
                <Typography variant="caption" color="text.secondary">
                  Days to Cover
                </Typography>
                <Typography variant="body2">
                  {formatNullableNumber(shortRatio, {
                    minimumFractionDigits: 1,
                    maximumFractionDigits: 1,
                  })}
                </Typography>
              </Stack>
              <Stack spacing={0.25}>
                <Typography variant="caption" color="text.secondary">
                  % of Float
                </Typography>
                <Typography variant="body2">
                  {shortPercentOfFloat === null
                    ? '—'
                    : `${(shortPercentOfFloat * 100).toFixed(1)}%`}
                </Typography>
              </Stack>
              <Stack spacing={0.25}>
                <Typography variant="caption" color="text.secondary">
                  Float Shares
                </Typography>
                <Typography variant="body2">
                  {formatNullableNumber(floatShares)}
                </Typography>
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      </Stack>

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
              valueInterpretation={insiderClustersHelp.interpretValue(
                insiderClusters ?? [],
              )}
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
    </Stack>
  )
}
