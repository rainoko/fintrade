// Shared TanStack Query key conventions for the daily-homework feature.
export const homeworkKeys = {
  today: ['daily-homework', 'today'] as const,
  yesterdaySuggestion: ['daily-homework', 'yesterday-suggestion'] as const,
}
