import { createTheme } from '@mui/material/styles'

/**
 * MUI theme augmentation: adds a `signal` palette (BUY/SELL/HOLD, per
 * docs/Analyse.md's Triple Screen signal output) and a `riskBreach` palette
 * entry (the portfolio 2%/6% risk-rule warning color, per Analyse.md §7-8
 * and Frontend.md's PositionsTable/RiskPanel). Components reference these
 * via `theme.palette.signal.buy` etc. instead of hard-coding hex values, so
 * every BUY/SELL/HOLD chip and risk banner in the app stays visually
 * consistent and themeable from one place.
 */
declare module '@mui/material/styles' {
  interface Palette {
    signal: {
      buy: string
      sell: string
      hold: string
    }
    riskBreach: {
      main: string
      background: string
    }
    divergence: {
      main: string
    }
    season: {
      spring: string
      summer: string
      autumn: string
      winter: string
    }
  }

  interface PaletteOptions {
    signal?: {
      buy: string
      sell: string
      hold: string
    }
    riskBreach?: {
      main: string
      background: string
    }
    divergence?: {
      main: string
    }
    season?: {
      spring: string
      summer: string
      autumn: string
      winter: string
    }
  }
}

export const theme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: '#1565c0',
    },
    secondary: {
      main: '#6a1b9a',
    },
    // BUY/SELL/HOLD: green/red/amber is the conventional finance-app
    // mapping and reads correctly against both the light background above
    // and MUI's default Chip/Alert components used to render them.
    signal: {
      buy: '#2e7d32',
      sell: '#c62828',
      hold: '#ed6c02',
    },
    // Portfolio risk-rule breach (total open risk > 6%, or a single new
    // position pushing equity risk > 2% — see Analyse.md §7). Deliberately
    // distinct from `signal.sell` so a risk breach banner never reads as
    // "this is a SELL signal" — it's a portfolio-level warning, not a
    // per-stock signal.
    riskBreach: {
      main: '#d32f2f',
      background: '#fdecea',
    },
    // Divergence markers/connecting line (PriceChart.tsx/OscillatorChart.tsx,
    // frontend-divergence-markers) -- one color for both bullish and
    // bearish divergences (distinguished by marker text/shape instead, see
    // that task's `decisions` entry), deliberately distinct from every
    // other color already in use on those charts: `signal.buy`/`signal.sell`
    // (the BUY/SELL transition markers this must read as visually different
    // from -- the whole point of this task), `warning.main` (false
    // breakouts), and `info.main` (the channel/value-zone overlay).
    divergence: {
      main: '#00897b',
    },
    // Indicator Seasons (docs/Analyse.md row 12, Elder ch. 32) -- deliberately
    // its own four-color set, distinct from `signal.buy`/`signal.sell`/
    // `signal.hold`: a season badge (common/SeasonBadge) is purely
    // informational (frontend-indicator-seasons-badge), so reusing the
    // BUY/SELL/HOLD colors would make it visually misreadable as a second,
    // conflicting signal on the same page. Loosely seasonal (green sprout /
    // gold sun / amber-brown leaf / pale blue frost) rather than
    // finance-conventional, since that's the whole visual point here.
    season: {
      spring: '#43a047',
      summer: '#f9a825',
      autumn: '#b8622e',
      winter: '#5e92c7',
    },
  },
  typography: {
    fontFamily: [
      '"Inter"',
      '-apple-system',
      'BlinkMacSystemFont',
      '"Segoe UI"',
      'Roboto',
      'Arial',
      'sans-serif',
    ].join(','),
  },
})
