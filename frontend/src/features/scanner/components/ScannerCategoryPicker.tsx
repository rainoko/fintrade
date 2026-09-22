import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import Button from '@mui/material/Button'
import FormControl from '@mui/material/FormControl'
import InputLabel from '@mui/material/InputLabel'
import MenuItem from '@mui/material/MenuItem'
import Select, { type SelectChangeEvent } from '@mui/material/Select'
import Stack from '@mui/material/Stack'
import type { ScannerCategory } from '../scannerCategories'

export interface ScannerCategoryPickerProps {
  /** IBKR's own scan categories, normalized by `toScannerCategories`. */
  categories: ScannerCategory[]
  /** Currently selected category's `code`, or `''` for none selected. */
  value: string
  onChange: (code: string) => void
  onRun: () => void
  /** Whether a scan is currently in flight — disables/spins the Run button. */
  running: boolean
}

/**
 * Category picker + "Run scan" action for the Scanner page (ScannerPanel):
 * a controlled `Select` over `categories` plus a button that fires `onRun`.
 * Purely presentational/controlled — owns no query or mutation state itself
 * (ScannerPanel does), matching AddPositionDialog/PositionsTable's own
 * "feature component owns hooks, its children are controlled" split.
 */
export default function ScannerCategoryPicker({
  categories,
  value,
  onChange,
  onRun,
  running,
}: ScannerCategoryPickerProps) {
  return (
    <Stack
      direction={{ xs: 'column', sm: 'row' }}
      spacing={2}
      sx={{ alignItems: { sm: 'center' } }}
    >
      <FormControl size="small" sx={{ minWidth: 260 }}>
        <InputLabel id="scanner-category-label">Scan category</InputLabel>
        <Select
          labelId="scanner-category-label"
          label="Scan category"
          value={value}
          onChange={(event: SelectChangeEvent) => onChange(event.target.value)}
        >
          {categories.map((category) => (
            <MenuItem key={category.code} value={category.code}>
              {category.label}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      <Button
        variant="contained"
        startIcon={<PlayArrowIcon />}
        disabled={!value}
        loading={running}
        onClick={onRun}
      >
        Run scan
      </Button>
    </Stack>
  )
}
