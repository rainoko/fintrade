import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Link from '@mui/material/Link'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { Link as RouterLink } from 'react-router-dom'
import { type MethodologyEntry, STATUS_META } from '../data/methodologyContent'

export interface MethodologyEntryCardProps {
  entry: MethodologyEntry
}

/**
 * Resolves a `MethodologyEntry.crossLinksTo` description to an actual
 * in-app route, so the card can render it as a clickable link instead of
 * plain prose (docs/tasks/frontend-methodology-explainer-followups.json's
 * `decisions` entry). Every `crossLinksTo` string in `methodologyContent.ts`
 * names its target page as its own leading segment ("Stock Detail page →
 * ...", "Portfolio page → ...", "Watchlist page → ..."), so this is a
 * simple, exhaustive prefix match rather than a separate structured field
 * per entry.
 *
 * The Stock Detail page (`/stocks/:ticker`) needs a concrete ticker this
 * page deliberately has no context for -- it explains the *methodology*
 * independent of any one ticker (see methodologyContent.ts's own docstring)
 * -- so a "Stock Detail page" cross-link routes to the Watchlist page
 * instead: the nearest page that lets a reader pick a concrete ticker and
 * continue on to Stock Detail from there, rather than a dead end. This is a
 * deliberately modest version of the fuller "deep-link straight to the
 * right ticker + auto-open the right MetricHelp popover" idea the review
 * finding also raised -- that would need a "which ticker" answer this page
 * has no source for, and a cross-page auto-open-popover mechanism that
 * doesn't exist anywhere else in the app yet; left as a further follow-up
 * rather than built here.
 */
function resolveCrossLinkPath(crossLinksTo: string): string | null {
  if (crossLinksTo.startsWith('Stock Detail page')) {
    return '/watchlist'
  }
  if (crossLinksTo.startsWith('Portfolio page')) {
    return '/portfolio'
  }
  if (crossLinksTo.startsWith('Watchlist page')) {
    return '/watchlist'
  }
  return null
}

/**
 * One indicator/technique's card on the Methodology Reference page: name +
 * citation + status chip, what it is, how it fits Elder's methodology, and
 * an honest "does this affect what you see today" statement -- the last of
 * which is this page's whole point (docs/tasks/frontend-methodology-
 * explainer.json's description). `crossLinksTo`, when present, points a
 * reader at the live, per-value `common/MetricHelp` explanation for the
 * same thing elsewhere in the app, rather than this page duplicating that
 * interpretive text (see this task's `decisions` entry) -- rendered as an
 * actual navigable link via `resolveCrossLinkPath` above, not just prose.
 */
export default function MethodologyEntryCard({ entry }: MethodologyEntryCardProps) {
  const statusMeta = STATUS_META[entry.appStatus]
  const crossLinkPath = entry.crossLinksTo ? resolveCrossLinkPath(entry.crossLinksTo) : null

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
            See it live:{' '}
            {crossLinkPath ? (
              <Link component={RouterLink} to={crossLinkPath}>
                {entry.crossLinksTo}
              </Link>
            ) : (
              entry.crossLinksTo
            )}
          </Typography>
        )}
      </CardContent>
    </Card>
  )
}
