import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { type MethodologyEntry, STATUS_META } from '../data/methodologyContent'

export interface MethodologyEntryCardProps {
  entry: MethodologyEntry
}

/**
 * One indicator/technique's card on the Methodology Reference page: name +
 * citation + status chip, what it is, how it fits Elder's methodology, and
 * an honest "does this affect what you see today" statement -- the last of
 * which is this page's whole point (docs/tasks/frontend-methodology-
 * explainer.json's description). `crossLinksTo`, when present, points a
 * reader at the live, per-value `common/MetricHelp` explanation for the
 * same thing elsewhere in the app, rather than this page duplicating that
 * interpretive text (see this task's `decisions` entry).
 */
export default function MethodologyEntryCard({ entry }: MethodologyEntryCardProps) {
  const statusMeta = STATUS_META[entry.appStatus]

  return (
    <Card variant="outlined" data-testid="methodology-entry-card">
      <CardContent>
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={1}
          sx={{ justifyContent: 'space-between', alignItems: { sm: 'flex-start' } }}
        >
          <Typography variant="h6" component="h3">
            {entry.name}
          </Typography>
          <Chip label={statusMeta.label} color={statusMeta.color} size="small" />
        </Stack>

        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
          {entry.citation}
        </Typography>

        <Typography variant="body2" sx={{ mb: 1 }}>
          {entry.summary}
        </Typography>

        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          {entry.elderContext}
        </Typography>

        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          In this app: {entry.appBehavior}
        </Typography>

        {entry.crossLinksTo && (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
            See it live: {entry.crossLinksTo}
          </Typography>
        )}
      </CardContent>
    </Card>
  )
}
