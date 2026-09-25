import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import PageHeader from '../components/common/PageHeader/PageHeader'
import TradingModeSettingsForm from '../features/settings/components/TradingModeSettingsForm'

/**
 * Settings (`/settings`, `frontend-day-trader-timeframe-mode-settings`) --
 * view/switch the app's global trading mode (Elder ch. 39's "Choosing
 * Timeframes -- the Factor of Five") between swing (weekly/daily, this
 * app's long-standing default) and day-trader (a user-configured
 * long-term/intermediate/short-term intraday timeframe triple), and
 * configure that triple when day-trader mode is selected. A standalone nav
 * destination -- see this task's `decisions` entry for why, over folding it
 * into an existing page. Stays thin per Frontend.md §3: all fetching and
 * business logic live in `features/settings/`.
 */
export default function SettingsPage() {
  return (
    <>
      <PageHeader title="Settings" />
      <Stack spacing={3}>
        <Typography variant="body1" color="text.secondary">
          Switch between swing (weekly/daily) and day-trader (intraday) trading modes. Day-trader
          mode requires a working IBKR Client Portal Gateway connection to compute real signals
          for stocks, watchlist, and portfolio pages -- see the IBKR status indicator in the
          toolbar.
        </Typography>
        <TradingModeSettingsForm />
      </Stack>
    </>
  )
}
