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
 * (docs/architecture/API.md#post-apidaily-homework). Invalidates both the
 * `today` query (so a re-render, e.g. after navigating away and back, shows
 * the freshly persisted entry rather than stale/absent data) and the
 * `history` query (`useDailyHomeworkHistory`, frontend-daily-homework-history)
 * — a successful submission always changes `GET /api/daily-homework`'s list
 * too, either adding today's row or overwriting its existing one.
 */
export function useRecordDailyHomework() {
  const queryClient = useQueryClient()

  return useMutation<DailyHomeworkOut, ApiError, DailyHomeworkIn>({
    mutationFn: recordDailyHomework,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: homeworkKeys.today })
      queryClient.invalidateQueries({ queryKey: homeworkKeys.history })
    },
  })
}
