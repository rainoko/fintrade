import CancelIcon from '@mui/icons-material/Cancel'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import HelpOutlineIcon from '@mui/icons-material/HelpOutlineOutlined'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemIcon from '@mui/material/ListItemIcon'
import ListItemText from '@mui/material/ListItemText'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import type { AnalysisResponse, Screens } from '../../../api/stocks'
import { explainSignal } from './signalExplanation'

export interface SignalExplanationContentProps {
  signal: AnalysisResponse['signal']
  screens: Screens
}

function ConditionIcon({ met }: { met: boolean | null }) {
  if (met === true) {
    return <CheckCircleIcon color="success" fontSize="small" />
  }
  if (met === false) {
    return <CancelIcon color="error" fontSize="small" />
  }
  return <HelpOutlineIcon color="disabled" fontSize="small" />
}

/**
 * Renders the causal "why this signal, for this ticker, right now" content
 * (`signalExplanation.ts`'s `explainSignal`) for `InfoBalloon`'s `content`
 * prop -- a headline plus one line per Triple Screen condition (Tide,
 * Impulse, Wave, Trigger), each marked met/not-met/uncertain. Feature
 * component (not `common/`): every condition here is an Elder Triple Screen
 * domain concept, same placement as ScreensPanel/SignalSummary.
 */
export default function SignalExplanationContent({
  signal,
  screens,
}: SignalExplanationContentProps) {
  const explanation = explainSignal(signal, screens)

  return (
    <Stack spacing={1} sx={{ maxWidth: 380 }}>
      <Typography variant="body2">{explanation.headline}</Typography>
      <List dense disablePadding aria-label="Signal condition breakdown">
        {explanation.conditions.map((condition) => (
          <ListItem key={condition.key} disableGutters alignItems="flex-start">
            <ListItemIcon sx={{ minWidth: 32, mt: 0.5 }}>
              <ConditionIcon met={condition.met} />
            </ListItemIcon>
            <ListItemText
              primary={condition.label}
              secondary={condition.detail}
              slotProps={{ secondary: { variant: 'caption' } }}
            />
          </ListItem>
        ))}
      </List>
    </Stack>
  )
}
