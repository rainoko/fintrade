import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { listDailyHomework, type DailyHomeworkListResponse } from '../../../api/homework'
import { homeworkKeys } from './queryKeys'

/**
 * `GET /api/daily-homework` (`operation_id: list_daily_homework`) — every
 * recorded self-test entry, most recent `date` first
 * (docs/architecture/API.md#get-apidaily-homework). Backs the history/trend
 * view of how "ready to trade" scores have looked over time
 * (`DailyHomeworkHistoryTable`).
 */
export function useDailyHomeworkHistory() {
  return useQuery<DailyHomeworkListResponse, ApiError>({
    queryKey: homeworkKeys.history,
    queryFn: listDailyHomework,
  })
}
