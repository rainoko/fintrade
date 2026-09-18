import Box from '@mui/material/Box'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useTheme } from '@mui/material/styles'
import type { ReactNode } from 'react'
import type { Screens } from '../../../api/stocks'
import MetricHelp from '../../../components/common/MetricHelp/MetricHelp'
import { formatNullableNumber, humanizeSnakeCase } from '../../../utils/format'
import { impulseHelp, tideHelp, triggerHelp, waveHelp } from './metricHelpContent'

export interface ScreensPanelProps {
  screens: Screens
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
      {/* A `<div>` (e.g. Impulse's Chip below) is invalid HTML nested inside
          a `<p>`, which is what `Typography variant="body2"` renders as by
          default — Box with an `sx.typography` style applies the same body2
          font styling via a `<div>` instead, so any child (plain text or a
          Chip) is always valid regardless of what a given caller passes. */}
      <Box sx={{ typography: 'body2' }}>{children}</Box>
    </Stack>
  )
}

interface ScreenSectionProps {
  title: string
  /** A `common/MetricHelp` trigger for this screen, rendered inline in the title row's right edge -- see this component's own doc comment. */
  help: ReactNode
  children: ReactNode
}

function ScreenSection({ title, help, children }: ScreenSectionProps) {
  return (
    <Card variant="outlined" sx={{ flex: '1 1 220px' }}>
      <CardContent>
        <Stack
          direction="row"
          spacing={1}
          sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1 }}
        >
          <Typography variant="subtitle2">{title}</Typography>
          {help}
        </Stack>
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
 *
 * Each `ScreenSection` gets a `common/MetricHelp` question-mark icon inline
 * in its title row (not an absolute corner overlay -- see this component's
 * own `ScreenSection`/`MetricHelp` doc comments) explaining what that
 * screen is, its Elder methodology basis, and an interpretation of this
 * ticker's current reading (`metricHelpContent.ts`,
 * frontend-stock-detail-metric-help).
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

  const stochasticKValue: number | null | undefined = wave.stochastic_k
  const stochasticIsKnown =
    stochasticKValue !== null && stochasticKValue !== undefined && !Number.isNaN(stochasticKValue)
  const stochasticNote = !stochasticIsKnown
    ? null
    : stochasticKValue < 30
      ? 'Oversold'
      : stochasticKValue > 70
        ? 'Overbought'
        : 'Neutral'

  return (
    <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap' }}>
      <ScreenSection
        title="Tide (Screen 1)"
        help={
          <MetricHelp
            metricLabel={tideHelp.metricLabel}
            definition={tideHelp.definition}
            elderContext={tideHelp.elderContext}
            valueInterpretation={tideHelp.interpretValue(
              tide.trend,
              tide.weekly_macd_histogram_slope,
            )}
          />
        }
      >
        <LabeledValue label="Trend">{humanizeSnakeCase(tide.trend)}</LabeledValue>
        <LabeledValue label="Weekly MACD-H slope">
          {humanizeSnakeCase(tide.weekly_macd_histogram_slope)}
        </LabeledValue>
      </ScreenSection>

      <ScreenSection
        title="Impulse System"
        help={
          <MetricHelp
            metricLabel={impulseHelp.metricLabel}
            definition={impulseHelp.definition}
            elderContext={impulseHelp.elderContext}
            valueInterpretation={impulseHelp.interpretValue(impulse)}
          />
        }
      >
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

      <ScreenSection
        title="Wave (Screen 2)"
        help={
          <MetricHelp
            metricLabel={waveHelp.metricLabel}
            definition={waveHelp.definition}
            elderContext={waveHelp.elderContext}
            valueInterpretation={waveHelp.interpretValue(
              stochasticKValue,
              wave.force_index_2ema,
              wave.state,
            )}
          />
        }
      >
        <LabeledValue label="Stochastic %K">
          {formatNullableNumber(stochasticKValue, {
            minimumFractionDigits: 1,
            maximumFractionDigits: 1,
          })}
          {stochasticNote ? ` (${stochasticNote})` : ''}
        </LabeledValue>
        <LabeledValue label="Force Index (2-EMA)">
          {formatNullableNumber(wave.force_index_2ema, { maximumFractionDigits: 1 })}
        </LabeledValue>
        <LabeledValue label="State">{humanizeSnakeCase(wave.state)}</LabeledValue>
      </ScreenSection>

      <ScreenSection
        title="Trigger (Screen 3)"
        help={
          <MetricHelp
            metricLabel={triggerHelp.metricLabel}
            definition={triggerHelp.definition}
            elderContext={triggerHelp.elderContext}
            valueInterpretation={triggerHelp.interpretValue(trigger.fired, trigger.reference)}
          />
        }
      >
        <LabeledValue label="Fired">{trigger.fired ? 'Yes' : 'No'}</LabeledValue>
        <LabeledValue label="Reference">{humanizeSnakeCase(trigger.reference)}</LabeledValue>
      </ScreenSection>
    </Stack>
  )
}
