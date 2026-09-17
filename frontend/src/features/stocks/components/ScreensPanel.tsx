import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'
import type { ReactNode } from 'react'
import type { Screens } from '../../../api/stocks'

export interface ScreensPanelProps {
  screens: Screens
}

function humanize(value: string): string {
  const words = value.replace(/_/g, ' ').toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

interface LabeledValueProps {
  label: string
  children: ReactNode
}

function LabeledValue({ label, children }: LabeledValueProps) {
  return (
    <Stack spacing={0.25}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2">{children}</Typography>
    </Stack>
  )
}

interface ScreenSectionProps {
  title: string
  children: ReactNode
}

function ScreenSection({ title, children }: ScreenSectionProps) {
  return (
    <Card variant="outlined" sx={{ flex: '1 1 220px' }}>
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>
          {title}
        </Typography>
        <Stack spacing={1.5}>{children}</Stack>
      </CardContent>
    </Card>
  )
}

/**
 * Structured, readable display of the four Triple Screen results
 * (docs/Analyse.md §2-5) from `GET /api/stocks/{ticker}/analysis`'s
 * `screens` object — one section per screen, plain labeled values rather
 * than a raw JSON dump. Feature component (not `common/`): every field here
 * (tide trend, impulse color, wave state, trigger reference) is an Elder
 * Triple Screen domain concept.
 */
export default function ScreensPanel({ screens }: ScreensPanelProps) {
  const theme = useTheme()
  const { tide, impulse, wave, trigger } = screens

  // Impulse's GREEN/RED/BLUE isn't a BUY/SELL/HOLD signal (common/SignalBadge's
  // prop type), so it gets its own small color mapping here rather than a
  // type-unsafe cast into SignalBadge — GREEN/RED/BLUE map onto the same
  // buy/sell/hold palette colors as a visual (not semantic) convenience,
  // since Green blocks fresh SELLs and Red blocks fresh BUYs the same way
  // signal.buy/signal.sell read on SignalBadge.
  const impulseColor =
    impulse === 'GREEN'
      ? theme.palette.signal.buy
      : impulse === 'RED'
        ? theme.palette.signal.sell
        : theme.palette.signal.hold

  const stochasticNote =
    wave.stochastic_k < 30 ? 'Oversold' : wave.stochastic_k > 70 ? 'Overbought' : 'Neutral'

  return (
    <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap' }}>
      <ScreenSection title="Tide (Screen 1)">
        <LabeledValue label="Trend">{humanize(tide.trend)}</LabeledValue>
        <LabeledValue label="Weekly MACD-H slope">
          {humanize(tide.weekly_macd_histogram_slope)}
        </LabeledValue>
      </ScreenSection>

      <ScreenSection title="Impulse System">
        <LabeledValue label="Color">
          <Chip
            label={impulse}
            size="small"
            style={{
              backgroundColor: impulseColor,
              color: theme.palette.getContrastText(impulseColor),
              fontWeight: 700,
            }}
          />
        </LabeledValue>
      </ScreenSection>

      <ScreenSection title="Wave (Screen 2)">
        <LabeledValue label="Stochastic %K">
          {wave.stochastic_k.toFixed(1)} ({stochasticNote})
        </LabeledValue>
        <LabeledValue label="Force Index (2-EMA)">
          {wave.force_index_2ema.toLocaleString(undefined, { maximumFractionDigits: 1 })}
        </LabeledValue>
        <LabeledValue label="State">{humanize(wave.state)}</LabeledValue>
      </ScreenSection>

      <ScreenSection title="Trigger (Screen 3)">
        <LabeledValue label="Fired">{trigger.fired ? 'Yes' : 'No'}</LabeledValue>
        <LabeledValue label="Reference">{humanize(trigger.reference)}</LabeledValue>
      </ScreenSection>
    </Stack>
  )
}
