import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { recordFollowUpReview, type ClosedTradeOut } from '../../../api/portfolio'
import { portfolioKeys } from './queryKeys'

export interface RecordFollowUpReviewVariables {
  tradeId: string
  followUpNotes: string
}

/**
 * `POST /api/portfolio/closed-trades/{trade_id}/follow-up-review` — records
 * Elder's mandatory two-months-later follow-up review for one closed trade
 * (ch. 59 Trade Journal Section E, docs/architecture/API.md). Invalidates
 * `portfolioKeys.all` so both the full trade-journal table and the
 * due-for-follow-up list (which this write should make the trade drop out
 * of, since `follow_up_reviewed_at` is no longer null) refetch immediately,
 * mirroring useAddPosition/useDeletePosition's own broad invalidation.
 */
export function useRecordFollowUpReview() {
  const queryClient = useQueryClient()

  return useMutation<ClosedTradeOut, ApiError, RecordFollowUpReviewVariables>({
    mutationFn: ({ tradeId, followUpNotes }) =>
      recordFollowUpReview(tradeId, { follow_up_notes: followUpNotes }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: portfolioKeys.all })
    },
  })
}
