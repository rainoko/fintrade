import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { deletePosition, type ExitReason } from '../../../api/portfolio'
import { portfolioKeys } from './queryKeys'

export interface DeletePositionVariables {
  id: string
  /** Elder's own exit-reason taxonomy — see DeletePositionParams.exitReason. */
  exitReason: ExitReason
  /** Optional manual override, must be supplied together with `exitDate` or not at all. */
  exitPrice?: number
  exitDate?: string
}

/**
 * `DELETE /api/portfolio/positions/{id}` — removes a position entirely (see
 * docs/architecture/API.md#delete-apiportfoliopositionsid). Invalidates the
 * portfolio query (and, via prefix-matching, the portfolio-risk query — see
 * queryKeys.ts) so the removed position and its contribution to equity/risk
 * disappear immediately rather than lingering until an unrelated refetch.
 *
 * Mutation variables carry `exitReason` and the optional `exitPrice`/
 * `exitDate` manual-exit override (frontend-close-position-dialog) — the
 * `id` moved from being the mutation's own sole argument into this object
 * once there was more than one thing to pass.
 */
export function useDeletePosition() {
  const queryClient = useQueryClient()

  return useMutation<void, ApiError, DeletePositionVariables>({
    mutationFn: ({ id, exitReason, exitPrice, exitDate }) =>
      deletePosition(id, { exitReason, exitPrice, exitDate }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: portfolioKeys.all })
    },
  })
}
