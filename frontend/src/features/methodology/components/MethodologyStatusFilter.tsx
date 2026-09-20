import Box from '@mui/material/Box'
import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import {
  type MethodologyStatus,
  STATUS_META,
  STATUS_ORDER,
} from '../data/methodologyContent'

export interface MethodologyStatusFilterProps {
  selected: ReadonlySet<MethodologyStatus>
  onToggle: (status: MethodologyStatus) => void
}

/**
 * Toggleable status legend/filter row for the Methodology Reference page
 * (`MethodologyPage.tsx`) -- one chip per `MethodologyStatus`, doubling as
 * both a legend (each chip's own tooltip-free description sits underneath,
 * since this is a reference page where hover-to-discover would hide
 * content rather than reveal it) and a click-to-filter control. Multiple
 * statuses can be active at once; the page treats an empty selection as
 * "show nothing matched" rather than silently falling back to "show all",
 * so a user filtering down to one status gets an honest reflection of
 * what's currently selected.
 *
 * Feature-specific, not `common/`: it's built directly around
 * `MethodologyStatus`, a domain concept of this one feature -- not a
 * general-purpose multi-select chip group Frontend.md §3's placement test
 * would put under `components/common/`.
 */
export default function MethodologyStatusFilter({
  selected,
  onToggle,
}: MethodologyStatusFilterProps) {
  return (
    <Box component="section" aria-label="Filter by implementation status">
      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
        {STATUS_ORDER.map((status) => {
          const meta = STATUS_META[status]
          const isSelected = selected.has(status)
          return (
            <Chip
              key={status}
              label={meta.label}
              color={meta.color}
              variant={isSelected ? 'filled' : 'outlined'}
              onClick={() => onToggle(status)}
              aria-pressed={isSelected}
            />
          )
        })}
      </Stack>
      <Stack spacing={0.5} sx={{ mt: 1.5 }}>
        {STATUS_ORDER.map((status) => (
          <Typography key={status} variant="caption" color="text.secondary">
            <strong>{STATUS_META[status].label}:</strong> {STATUS_META[status].description}
          </Typography>
        ))}
      </Stack>
    </Box>
  )
}
