import Alert from '@mui/material/Alert'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import type { ExtendedDataOut, InsiderTransactionOut } from '../../../api/stocks'
import DataTable, {
  type DataTableColumn,
} from '../../../components/common/DataTable/DataTable'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import StatCard from '../../../components/common/StatCard/StatCard'
import { formatDate, formatNullableCurrency, formatNullableNumber } from '../../../utils/format'
import {
  earningsDateHelp,
  exDividendDateHelp,
  fundamentalDataUnavailableHelp,
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
}

interface InsiderRow extends InsiderTransactionOut {
  _key: string
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
 */
export default function FundamentalDataPanel({ extendedData }: FundamentalDataPanelProps) {
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
            Earnings/dividend dates, short interest, and insider transactions aren’t available
            for this ticker right now -- the fallback (Stooq) market data provider is currently
            serving this ticker and has no equivalent for this data. This is distinct from
            “checked, nothing found.”
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
            Earnings expected {earningsDate} -- within the next 14 days. A nasty surprise can
            gap straight through a protective stop; see the Earnings Date help below for
            Elder&rsquo;s own reasoning.
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
                <Typography variant="body2">{formatNullableNumber(sharesShort)}</Typography>
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
                <Typography variant="body2">{formatNullableNumber(floatShares)}</Typography>
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
              valueInterpretation={insiderTransactionsHelp.interpretValue(insiderTransactions)}
            />
          </Stack>
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
