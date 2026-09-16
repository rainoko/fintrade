import Box from '@mui/material/Box'
import LinearProgress from '@mui/material/LinearProgress'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'
import { confidenceBand } from './confidenceBand'

export interface ConfidenceGaugeProps {
  /** Confidence score, 0-100 (docs/Analyse.md §6 — a rule-based composite, not a probability). */
  confidence: number
}

/**
 * 0-100 confidence display with Low/Medium/High band coloring
 * (docs/Analyse.md §6). Always shows the raw percentage alongside the band
 * label, per Analyse.md's note that the band is a display aid, not a
 * replacement for the number.
 */
export default function ConfidenceGauge({ confidence }: ConfidenceGaugeProps) {
  const theme = useTheme()
  const band = confidenceBand(confidence)
  const clamped = Math.min(100, Math.max(0, confidence))

  const color =
    band === 'Low'
      ? theme.palette.signal.sell
      : band === 'Medium'
        ? theme.palette.signal.hold
        : theme.palette.signal.buy

  return (
    <Box sx={{ minWidth: 160 }}>
      <Stack direction="row" sx={{ justifyContent: 'space-between', mb: 0.5 }}>
        <Typography variant="body2" color="text.secondary">
          Confidence
        </Typography>
        <Typography variant="body2" sx={{ fontWeight: 700, color }}>
          {confidence}% &middot; {band}
        </Typography>
      </Stack>
      <LinearProgress
        variant="determinate"
        value={clamped}
        role="progressbar"
        aria-label="Confidence"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        sx={{
          height: 8,
          borderRadius: 4,
          backgroundColor: theme.palette.action.disabledBackground,
          '& .MuiLinearProgress-bar': { backgroundColor: color },
        }}
      />
    </Box>
  )
}
