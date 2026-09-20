import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import type { MethodologySection } from '../data/methodologyContent'
import MethodologyEntryCard from './MethodologyEntryCard'

export interface MethodologySectionViewProps {
  section: MethodologySection
}

/**
 * One Triple-Screen-taxonomy section of the Methodology Reference page: a
 * heading + intro paragraph (Elder's own framing for this screen/rule, or
 * the whole-page overview), followed by a card per entry already filtered
 * down to the caller's currently-selected statuses. Renders nothing for an
 * entries-bearing section with zero entries left after filtering (the
 * intro-only "Overview" section, which never has entries, always renders)
 * -- `MethodologyPage` decides whether to render this component at all,
 * per section, based on that same filtered count, so this component itself
 * stays a pure "given this section, show it" renderer.
 */
export default function MethodologySectionView({ section }: MethodologySectionViewProps) {
  return (
    <Stack component="section" spacing={2} aria-labelledby={`methodology-section-${section.id}`}>
      <Typography variant="h5" component="h2" id={`methodology-section-${section.id}`}>
        {section.title}
      </Typography>
      <Typography variant="body1" color="text.secondary">
        {section.intro}
      </Typography>
      {section.entries.length > 0 && (
        <Stack spacing={2}>
          {section.entries.map((entry) => (
            <MethodologyEntryCard key={entry.id} entry={entry} />
          ))}
        </Stack>
      )}
    </Stack>
  )
}
