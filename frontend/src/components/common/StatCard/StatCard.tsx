import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward'
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'

export type StatCardDeltaDirection = 'positive' | 'negative' | 'neutral'

export interface StatCardDelta {
  /** Pre-formatted delta text, e.g. '+3.20%' or '-1 position'. */
  text: string
  direction: StatCardDeltaDirection
}

export interface StatCardProps {
  /** Short label describing what `value` represents, e.g. 'Total Equity'. */
  label: string
  /** The headline value, already formatted for display. */
  value: string
  /** Optional trend/delta shown under the value (e.g. change since yesterday). */
  delta?: StatCardDelta
}

/**
 * Generic label + value stat card used for equity/risk summary tiles
 * (Dashboard, Portfolio risk panel). Takes only pre-formatted display
 * strings — it doesn't know what "equity" or "risk" mean, just how to lay
 * out a label/value/delta.
 */
export default function StatCard({ label, value, delta }: StatCardProps) {
  const theme = useTheme()

  const deltaColor =
    delta?.direction === 'positive'
      ? theme.palette.success.main
      : delta?.direction === 'negative'
        ? theme.palette.error.main
        : theme.palette.text.secondary

  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="body2" color="text.secondary" gutterBottom>
          {label}
        </Typography>
        <Typography variant="h5" component="p">
          {value}
        </Typography>
        {delta && (
          <Stack
            direction="row"
            spacing={0.5}
            sx={{ alignItems: 'center', mt: 0.5, color: deltaColor }}
          >
            {delta.direction === 'positive' && <ArrowUpwardIcon fontSize="inherit" />}
            {delta.direction === 'negative' && <ArrowDownwardIcon fontSize="inherit" />}
            <Typography variant="body2" component="span" sx={{ color: 'inherit' }}>
              {delta.text}
            </Typography>
          </Stack>
        )}
      </CardContent>
    </Card>
  )
}
