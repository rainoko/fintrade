import Box from '@mui/material/Box'
import LinearProgress from '@mui/material/LinearProgress'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'
import { confidenceBand, type ConfidenceBand } from './confidenceBand'

export interface ConfidenceGaugeProps {
  /** Confidence score, 0-100 (docs/Analyse.md §6 — a rule-based composite, not a probability). */
  confidence: number
  /**
   * Pre-computed Low/Medium/High band, e.g. the API's own `confidence_band`
   * field (see AnalysisResponse in api/types.ts). When provided, this is
   * used as-is instead of re-deriving a band from `confidence` client-side,
   * so a caller wired to real Signal data can't silently drift from the
   * backend's confidence_band.py rule if that rule is ever revised. Falls
   * back to local computation (confidenceBand.ts) only when omitted, e.g.
   * for Storybook/tests that only have a raw number on hand.
   */
  band?: ConfidenceBand
}

/**
 * 0-100 confidence display with Low/Medium/High band coloring
 * (docs/Analyse.md §6). Always shows the raw percentage alongside the band
 * label, per Analyse.md's note that the band is a display aid, not a
 * replacement for the number.
 */
export default function ConfidenceGauge({ confidence, band: bandProp }: ConfidenceGaugeProps) {
  const theme = useTheme()
  const clamped = Math.min(100, Math.max(0, confidence))
  const band = bandProp ?? confidenceBand(clamped)

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
          {clamped}% &middot; {band}
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
