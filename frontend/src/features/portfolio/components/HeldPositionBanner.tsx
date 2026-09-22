import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import Box from '@mui/material/Box'
import Stack from '@mui/material/Stack'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import { formatCurrency } from '../../../utils/format'
import { usePortfolio } from '../hooks/usePortfolio'
import { usePortfolioRisk } from '../hooks/usePortfolioRisk'
import PositionProfitTargetCell from './PositionProfitTargetCell'

export interface HeldPositionBannerProps {
  /** Normalized (trimmed + uppercased) ticker currently being viewed. */
  ticker: string
}

/**
 * "You hold this position" context banner for the Stock Detail page
 * (`frontend-position-risk-columns`) -- shows entry price/quantity/date plus
 * the position's current protective stop and profit target when the viewed
 * ticker is one of the user's open positions, so the answer to "am I holding
 * this, and at what stop/target?" doesn't require navigating away to the
 * Portfolio page. Renders nothing for a ticker that isn't held.
 *
 * Lives under `features/portfolio/components/` rather than
 * `features/stocks/components/` despite being consumed from
 * `pages/StockDetailPage.tsx`: every field it renders (a position's entry
 * price, `RiskPosition.protective_stop`/`profit_target`) is a portfolio
 * domain concept it fetches itself via `usePortfolio`/`usePortfolioRisk`,
 * not something the stock-analysis endpoints know about -- the same
 * cross-feature placement `TradeApgarDialog` already established for this
 * exact page (a portfolio-domain component, imported and rendered from the
 * stock detail page). See this task's `decisions` entry.
 *
 * Fetches independently of `StockDetailPage`'s own `useStockAnalysis` call
 * (rather than being gated on it) -- whether a ticker is held is a portfolio
 * fact, unrelated to whether that ticker's analysis endpoint happens to
 * succeed for the current request, so a transient/permanent analysis failure
 * (503/404/422) shouldn't also hide the fact that the user holds it. `null`
 * is returned (not a loading/error state of its own) whenever the position
 * isn't found or `usePortfolio` hasn't resolved yet -- a supplementary
 * context panel silently staying absent until its data is available is
 * preferable to a second loading spinner competing with the page's main
 * one. See this task's `decisions` entry.
 *
 * A genuine `riskQuery.isError` (as opposed to a held position simply being
 * absent from a *successful* risk response) is handled explicitly rather
 * than falling through to the same '—' used for "no stop/target configured
 * yet": this page (Stock Detail) has no `RiskPanel`/`PositionsTable`
 * equivalent of its own to surface the failure elsewhere, so silently
 * showing '—' here would misrepresent a fetch failure as "this position
 * has no stop" -- a materially different, worse claim for a page whose
 * whole point is telling the user their actual stop/target. Both the
 * Current Stop and Profit Target fields instead show a small inline warning
 * icon (`WarningAmberIcon` in a `Tooltip`, the same
 * icon-plus-tooltip-for-a-degraded-state pattern `common/IbkrStatusBadge`
 * already uses) with the backend's own `error.detail` as the tooltip text,
 * rather than a second full-page `ErrorState` block competing with
 * `StockDetailPage`'s own error handling for `useStockAnalysis`. See this
 * task's `decisions` entry (corrected against
 * `frontend-position-risk-columns-followups`, which found the previous
 * version of this comment's "already surfaced loudly ... on the Portfolio
 * page itself" claim was inaccurate).
 *
 * The Profit Target figure reuses `PositionProfitTargetCell` (RiskPanel's
 * own column, `RiskPosition.profit_target` -- computed for every open
 * position regardless of its current live signal, unlike
 * `AnalysisResponse.profit_target`) rather than the stock-detail page's own
 * `ProfitTargetDisplay` (which takes a `signal` prop and interprets a null
 * target as "not a fresh BUY signal", the wrong explanation for an
 * already-open position). See this task's `decisions` entry.
 */
export default function HeldPositionBanner({ ticker }: HeldPositionBannerProps) {
  const portfolioQuery = usePortfolio()
  const riskQuery = usePortfolioRisk()

  const position = portfolioQuery.data?.positions.find(
    (candidate) => candidate.ticker === ticker,
  )

  if (!position) {
    return null
  }

  const riskPosition = riskQuery.data?.positions.find(
    (candidate) => candidate.ticker === ticker,
  )

  // A genuine GET /api/portfolio/risk failure -- rendered as a small inline
  // warning icon/tooltip on both affected fields below instead of falling
  // through to their normal '—' ("no stop/target configured") case. See
  // this component's own doc comment above. Current Stop and Profit Target
  // get distinct, field-specific `aria-label`s (rather than sharing one
  // "Risk data unavailable" label) so a screen reader user encountering
  // either icon on its own -- e.g. navigating by landmark/label rather than
  // reading the whole banner in document order -- can tell which field
  // failed without relying on surrounding visual/DOM context.
  const stopDataError = riskQuery.isError ? (
    <Tooltip
      title={`Protective stop unavailable: ${riskQuery.error.detail}`}
    >
      <WarningAmberIcon
        fontSize="small"
        color="warning"
        aria-label="Current Stop unavailable"
        data-testid="held-position-stop-error"
      />
    </Tooltip>
  ) : null

  const profitTargetDataError = riskQuery.isError ? (
    <Tooltip
      title={`Profit target unavailable: ${riskQuery.error.detail}`}
    >
      <WarningAmberIcon
        fontSize="small"
        color="warning"
        aria-label="Profit target unavailable"
        data-testid="held-position-profit-target-error"
      />
    </Tooltip>
  ) : null

  return (
    <Box
      role="note"
      aria-label="You hold this position"
      sx={{
        p: 2,
        mb: 3,
        borderRadius: 1,
        border: '1px solid',
        borderColor: 'divider',
        backgroundColor: 'action.hover',
      }}
    >
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
        You hold this position
      </Typography>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={3}>
        <Box>
          <Typography variant="caption" color="text.secondary" component="div">
            Entry Price
          </Typography>
          <Typography variant="body2">
            {formatCurrency(position.avg_cost_basis)} · {position.quantity} sh ·{' '}
            {position.entry_date}
          </Typography>
        </Box>
        <Box>
          <Typography variant="caption" color="text.secondary" component="div">
            Current Stop
          </Typography>
          <Typography
            variant="body2"
            sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}
          >
            {stopDataError ?? (riskPosition ? formatCurrency(riskPosition.protective_stop) : '—')}
          </Typography>
        </Box>
        <Box>
          <Typography variant="caption" color="text.secondary" component="div">
            Profit Target
          </Typography>
          {profitTargetDataError ?? (
            <PositionProfitTargetCell
              profitTarget={riskPosition?.profit_target ?? null}
            />
          )}
        </Box>
      </Stack>
    </Box>
  )
}
