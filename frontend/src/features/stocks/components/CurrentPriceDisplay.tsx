import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import PercentChange from '../../../components/common/PercentChange/PercentChange'
import { formatCurrency } from '../../../utils/format'

export interface CurrentPriceDisplayProps {
  /** `AnalysisResponse.current_price` -- the ticker's latest daily closing price. */
  currentPrice: number
  /**
   * `AnalysisResponse.current_price_change_pct` -- day-over-day change versus
   * the prior daily bar's close, as a percentage (e.g. 2.5 for +2.5%). Null
   * when there's no prior bar to diff against (see that field's own
   * description) -- the delta is simply omitted in that case, rather than
   * showing a misleading 0%/placeholder.
   */
  changePct: number | null
}

/**
 * Large, bold current-price readout for the Stock Detail page
 * (frontend-stock-detail-current-price-prominent) -- rendered directly below
 * `PageHeader`, above the methodology/Trade-Apgar action row, so it's the
 * first thing visible after the ticker name itself and doesn't require
 * scrolling down to `StockCharts`' own candlestick pane to see today's
 * price. See that task's `decisions` entry for why this placement was
 * chosen over embedding the price inside `PageHeader`'s own title area (and
 * for why the day-over-day change is included rather than scoped out).
 *
 * Feature component (not `common/`) since it's specific to this one
 * `AnalysisResponse`-shaped pairing of fields, unlike the domain-agnostic
 * `common/PercentChange` it composes for the colored delta.
 */
export default function CurrentPriceDisplay({
  currentPrice,
  changePct,
}: CurrentPriceDisplayProps) {
  return (
    <Stack direction="row" spacing={1.5} sx={{ alignItems: 'baseline', mb: 2 }}>
      <Typography variant="h4" component="p" data-testid="current-price" sx={{ fontWeight: 700 }}>
        {formatCurrency(currentPrice)}
      </Typography>
      {changePct !== null && <PercentChange value={changePct} />}
    </Stack>
  )
}
