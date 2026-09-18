import Link from '@mui/material/Link'
import { Link as RouterLink } from 'react-router-dom'

export interface TickerLinkProps {
  /** Ticker symbol to display and link to, e.g. 'AAPL'. */
  ticker: string
}

/**
 * Renders a ticker symbol as a link into that ticker's stock detail page
 * (`/stocks/:ticker`), URI-encoded so a symbol containing characters like
 * `.`/`-` (e.g. 'BRK.B') still produces a valid path segment. The single
 * shared way a ticker is displayed anywhere it's a *reference* to another
 * page (a position row, a watchlist row, a risk row) — not for the
 * current page's own subject (e.g. StockDetailPage's own header, or the text
 * typed into TickerSearchBox), which isn't a reference to a different page
 * and shouldn't link to itself (frontend-ticker-link task description).
 */
export default function TickerLink({ ticker }: TickerLinkProps) {
  return (
    <Link component={RouterLink} to={`/stocks/${encodeURIComponent(ticker)}`}>
      {ticker}
    </Link>
  )
}
