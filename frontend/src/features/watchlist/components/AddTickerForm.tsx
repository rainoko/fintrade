import AddIcon from '@mui/icons-material/Add'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import { useState, type FormEvent } from 'react'
import ErrorState from '../../../components/common/ErrorState/ErrorState'
import { useAddWatchlistItem } from '../hooks/useAddWatchlistItem'

/**
 * Add-ticker control for the Watchlist page: a single-field inline form
 * (not a modal dialog, unlike portfolio's AddPositionDialog) since
 * `POST /api/watchlist` takes only `ticker` and — being an idempotent no-op
 * on a duplicate add (API.md) with no merge outcome worth summarizing the
 * way a portfolio-position quantity/cost-basis merge is — has nothing extra
 * to confirm before returning to the list. See this task's `decisions` entry.
 *
 * The submit button's `loading` state now spans the *entire* add flow, not
 * just the POST — useAddWatchlistItem's own `onSuccess` awaits the
 * invalidated watchlist refetch, so `isPending` (and this button) stays true
 * until the new ticker's signal has actually been (re)computed. During that
 * same window, WatchlistTable independently renders an animated skeleton
 * placeholder row for the ticker being added (frontend-watchlist-add-skeleton)
 * — see that component and useAddWatchlistItem's doc comments.
 */
export default function AddTickerForm() {
  const [value, setValue] = useState('')
  const addWatchlistItem = useAddWatchlistItem()
  const trimmed = value.trim()

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!trimmed) {
      return
    }
    addWatchlistItem.mutate(
      { ticker: trimmed.toUpperCase() },
      { onSuccess: () => setValue('') },
    )
  }

  return (
    <Stack spacing={1} sx={{ width: { xs: '100%', sm: 320 } }}>
      <Stack component="form" direction="row" spacing={1} onSubmit={handleSubmit}>
        <TextField
          label="Add ticker to watchlist"
          placeholder="e.g. AAPL"
          size="small"
          fullWidth
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
        <Button
          type="submit"
          variant="contained"
          startIcon={<AddIcon />}
          disabled={!trimmed}
          loading={addWatchlistItem.isPending}
        >
          Add
        </Button>
      </Stack>
      {addWatchlistItem.isError && <ErrorState error={addWatchlistItem.error} />}
    </Stack>
  )
}
