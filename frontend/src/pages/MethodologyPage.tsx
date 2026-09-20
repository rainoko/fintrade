import Alert from '@mui/material/Alert'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import { useState } from 'react'
import PageHeader from '../components/common/PageHeader/PageHeader'
import {
  METHODOLOGY_SECTIONS,
  STATUS_ORDER,
  type MethodologySection,
  type MethodologyStatus,
} from '../features/methodology/data/methodologyContent'
import MethodologySectionView from '../features/methodology/components/MethodologySectionView'
import MethodologyStatusFilter from '../features/methodology/components/MethodologyStatusFilter'

function filterSection(
  section: MethodologySection,
  selected: ReadonlySet<MethodologyStatus>,
): MethodologySection | null {
  // The overview section carries no entries at all -- it's pure framing
  // text, always shown regardless of the status filter.
  if (section.entries.length === 0) {
    return section
  }
  const entries = section.entries.filter((entry) => selected.has(entry.appStatus))
  if (entries.length === 0) {
    return null
  }
  return { ...section, entries }
}

/**
 * "Signals we considered" -- a standalone Elder-methodology reference page
 * (`/methodology`, `frontend-methodology-explainer`), reachable from the
 * main navigation (`NavDrawer`) and from the Stock Detail page. Purely
 * static/local content (`features/methodology/data/methodologyContent.ts`)
 * grounded directly in `docs/Analyse.md` and `docs/ideas.md` -- no API call,
 * unlike every other page in this app, since there's no server-side data
 * behind "what does this app's methodology consist of."
 *
 * Structure decision (recorded in this task's `decisions` entry): sections
 * follow Elder's own Triple Screen taxonomy (Screen 1/2/3, Impulse,
 * Confidence, Portfolio Risk), the same structure `docs/Analyse.md` itself
 * uses, with two catch-all sections at the end -- "Other Indicators" (built
 * and exposed, not yet wired into the signal) and "Considered But Not (Yet)
 * Implemented" (docs/ideas.md). Implementation status is a second,
 * filterable dimension across all of that (`MethodologyStatusFilter`) --
 * both axes from the task's checklist, rather than choosing one over the
 * other.
 */
export default function MethodologyPage() {
  const [selectedStatuses, setSelectedStatuses] = useState<Set<MethodologyStatus>>(
    () => new Set(STATUS_ORDER),
  )

  function toggleStatus(status: MethodologyStatus) {
    setSelectedStatuses((previous) => {
      const next = new Set(previous)
      if (next.has(status)) {
        next.delete(status)
      } else {
        next.add(status)
      }
      return next
    })
  }

  const filteredSections = METHODOLOGY_SECTIONS.map((section) =>
    filterSection(section, selectedStatuses),
  ).filter((section): section is MethodologySection => section !== null)

  return (
    <>
      <PageHeader title="Signals We Considered" />

      <Stack spacing={4}>
        <Typography variant="body1" color="text.secondary">
          Every signal, indicator, and money-management rule this app is aware of from Dr.
          Alexander Elder&apos;s Triple Screen methodology -- what it is, the book/chapter it
          comes from, and an honest statement of whether (and how) it currently affects the
          BUY/SELL/HOLD signal, the confidence score, or the portfolio risk rules you see
          elsewhere in this app. Grounded directly in{' '}
          <code>docs/Analyse.md</code> (what this app computes) and <code>docs/ideas.md</code>{' '}
          (everything considered but not yet built).
        </Typography>

        <MethodologyStatusFilter selected={selectedStatuses} onToggle={toggleStatus} />

        {selectedStatuses.size === 0 && (
          <Alert severity="info">
            No status is selected, so no indicator/technique entries are shown below. Select at
            least one status chip above to see matching entries.
          </Alert>
        )}

        {filteredSections.map((section) => (
          <MethodologySectionView key={section.id} section={section} />
        ))}
      </Stack>
    </>
  )
}
