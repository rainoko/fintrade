import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

/**
 * Ticker lookup: a text field + submit button that navigates to
 * `/stocks/:ticker` (StockDetailPage). Feature component (not `common/`)
 * since it's tied to this app's ticker-routing convention, not a generic
 * search box.
 *
 * This is the single entry point into stock analysis — built here
 * (frontend-dashboard-page) because frontend-stock-analysis-page, which
 * would otherwise own deciding where this lives, hadn't landed yet when
 * this task needed it. DashboardPage renders it directly; when
 * frontend-stock-analysis-page lands it should reuse this component (e.g.
 * on StockDetailPage itself, or promoted into AppShell) rather than
 * building a second ticker entry point — see this task's `decisions` entry.
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
