import Alert from '@mui/material/Alert'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import type { ExtendedDataOut } from '../../../api/stocks'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import StatCard from '../../../components/common/StatCard/StatCard'
import { formatDate, formatNullableNumber } from '../../../utils/format'
import {
  earningsDateHelp,
  exDividendDateHelp,
  fundamentalDataUnavailableHelp,
  shortInterestHelp,
} from './metricHelpContent'

export interface FundamentalDataPanelProps {
  /**
   * `AnalysisResponse.extended_data` -- a genuinely non-optional,
   * non-nullable field per `backend/app/api/schemas.py` and the generated
   * `ExtendedDataOut` type, so a real backend response always supplies it.
   * Tightened to match that contract exactly (frontend-fundamental-data-
   * panel-followups): the `StockDetailPage.test.tsx` SELL/HOLD/season/
   * normalize fixtures that used to hand-roll a partial `AnalysisResponse`
   * omitting this field have been synced to include it, so the
   * `if (!extendedData) return null` guard this type used to require is no
   * longer needed and has been removed.
   */
  extendedData: ExtendedDataOut
}

/**
 * Earnings/dividend dates and short interest for the current ticker
 * (`AnalysisResponse.extended_data`, backend-market-data-extra-fields) --
 * purely informational context never read by signal/confidence computation
 * (confirmed in that task's own review; every `metricHelpContent.ts` entry
 * this panel uses says so explicitly too). Feature component (not
 * `common/`): every field here is a ticker-specific fundamental-data concept
 * tied directly to `AnalysisResponse`.
 *
 * Insider Transactions (`AnalysisResponse.insider_transactions`/
 * `insider_clusters`) used to be this panel's own last `Card` but has moved
 * out into its own sibling component, `InsiderTransactionsPanel`, rendered
 * by `StockDetailPage` as the LAST block on the page, after `StockCharts`
 * (frontend-stock-detail-insider-transactions-last) -- see this task's
 * `decisions` entry for why: the top-of-page placement below is motivated
 * specifically by the earnings-date warning banner, not by Insider
 * Transactions, which was simply the last thing rendered inside this panel
 * as an implementation detail of how it happened to be composed.
 *
 * Placement decision (frontend-fundamental-data-panel's own `decisions`
 * entry): rendered directly below `SignalSummary` on `StockDetailPage`,
 * ahead of `ScreensPanel`/`IndicatorsPanel`/`StockCharts` -- so the
 * earnings-date warning banner below, the highest-value piece per that
 * task's own description ("a nasty earnings surprise can do serious damage
 * to your position... can jump straight past any stop level", Elder
 * ch. 58), is immediately visible near the top of the page rather than
 * buried below several other panels and the price chart.
 *
 * Handles `unavailable_reason === 'fallback_provider_active'` as an
 * explicit, visually distinct state (a dashed-border card naming the cause)
 * rather than silently rendering every field as an unadorned '—' the same
 * way a genuine "checked yfinance, found nothing" null would -- see
 * frontend-fundamental-data-panel's `decisions` entry for why that
 * distinction matters here. This branch no longer mentions insider
 * transactions (`InsiderTransactionsPanel` renders its own equivalent
 * unavailable state for that, consulting the same
 * `extendedData.unavailable_reason`).
 */
export default function FundamentalDataPanel({
  extendedData,
}: FundamentalDataPanelProps) {
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
            Earnings/dividend dates and short interest aren’t available for this ticker
            right now -- the fallback (Stooq) market data provider is currently serving
            this ticker and has no equivalent for this data. This is distinct from
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
  } = extendedData

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
    </Stack>
  )
}
