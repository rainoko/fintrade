import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

/**
 * Ticker lookup: a text field + submit button that navigates to
 * `/stocks/:ticker` (StockDetailPage). Feature component (not `common/`)
 * since it hardcodes this app's `/stocks/:ticker` route and a
 * ticker-normalization convention (uppercase, trim) — stock-domain
 * knowledge, not a generic "search box" (see Frontend.md §3's placement
 * rule).
 *
 * This is the app's single entry point into stock analysis, built by
 * frontend-dashboard-page (before this task existed to decide where it
 * lived) and reused as-is by both DashboardPage and StockDetailPage
 * (frontend-stock-analysis-page) rather than each building its own copy —
 * see frontend-stock-analysis-page's `decisions` entry for why it stayed
 * under features/stocks/ instead of moving to components/common/ once a
 * second consumer appeared.
 */
export default function TickerSearchBox() {
  const navigate = useNavigate()
  const [value, setValue] = useState('')
  const trimmed = value.trim()

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!trimmed) {
      return
    }
    navigate(`/stocks/${encodeURIComponent(trimmed.toUpperCase())}`)
    setValue('')
  }

  return (
    <Stack
      component="form"
      direction="row"
      spacing={1}
      onSubmit={handleSubmit}
      sx={{ width: { xs: '100%', sm: 320 } }}
    >
      <TextField
        label="Look up a ticker"
        placeholder="e.g. AAPL"
        size="small"
        fullWidth
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
      <Button type="submit" variant="contained" disabled={!trimmed}>
        Go
      </Button>
    </Stack>
  )
}
