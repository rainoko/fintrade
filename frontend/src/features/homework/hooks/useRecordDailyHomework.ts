import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import {
  recordDailyHomework,
  type DailyHomeworkIn,
  type DailyHomeworkOut,
} from '../../../api/homework'
import { homeworkKeys } from './queryKeys'

/**
 * `POST /api/daily-homework` — records (or overwrites) a day's five scores
 * (docs/architecture/API.md#post-apidaily-homework). Invalidates the
 * `today` query so a re-render (e.g. after navigating away and back) shows
 * the freshly persisted entry rather than stale/absent data.
 */
export function useRecordDailyHomework() {
  const queryClient = useQueryClient()

  return useMutation<DailyHomeworkOut, ApiError, DailyHomeworkIn>({
    mutationFn: recordDailyHomework,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: homeworkKeys.today }),
  })
}
