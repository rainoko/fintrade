import Box from '@mui/material/Box'
import Stack from '@mui/material/Stack'
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
 * one, and a `usePortfolio`/`usePortfolioRisk` fetch failure here is already
 * surfaced loudly by `RiskPanel`/`PositionsTable` on the Portfolio page
 * itself. See this task's `decisions` entry.
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
          <Typography variant="body2">
            {riskPosition ? formatCurrency(riskPosition.protective_stop) : '—'}
          </Typography>
        </Box>
        <Box>
          <Typography variant="caption" color="text.secondary" component="div">
            Profit Target
          </Typography>
          <PositionProfitTargetCell
            profitTarget={riskPosition?.profit_target ?? null}
          />
        </Box>
      </Stack>
    </Box>
  )
}
