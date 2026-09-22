import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { getDailyHomeworkToday, type DailyHomeworkTodayResponse } from '../../../api/homework'
import { homeworkKeys } from './queryKeys'

/**
 * `GET /api/daily-homework/today` — today's recorded self-test entry, if
 * any (docs/architecture/API.md#get-apidaily-homeworktoday). Used to
 * pre-fill the form with today's already-recorded answers rather than
 * always starting blank (`DailyHomeworkForm`).
 */
export function useDailyHomeworkToday() {
  return useQuery<DailyHomeworkTodayResponse, ApiError>({
    queryKey: homeworkKeys.today,
    queryFn: getDailyHomeworkToday,
  })
}
