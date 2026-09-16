export type ConfidenceBand = 'Low' | 'Medium' | 'High'

/**
 * Confidence band per docs/Analyse.md §6's suggested display bands:
 * <40% = Low, 40-70% = Medium, >70% = High. Colocated with (but split out
 * of) ConfidenceGauge.tsx so the component file only exports the component
 * itself (react-refresh/only-export-components) while this pure function
 * stays independently unit-testable.
 */
export function confidenceBand(confidence: number): ConfidenceBand {
  if (confidence < 40) {
    return 'Low'
  }
  if (confidence <= 70) {
    return 'Medium'
  }
  return 'High'
}
