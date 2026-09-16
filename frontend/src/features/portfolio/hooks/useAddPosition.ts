import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { addPosition, type PositionIn, type PositionOut } from '../../../api/portfolio'
import { portfolioKeys } from './queryKeys'

/**
 * `POST /api/portfolio/positions` — add a position, or merge into an
 * existing one for the same ticker (docs/architecture/API.md#post-apiportfoliopositions).
 * Invalidates the portfolio query (and, via prefix-matching on
 * `portfolioKeys.all`, the portfolio-risk query once it exists — see
 * queryKeys.ts) so a write is immediately reflected everywhere it's shown.
 */
export function useAddPosition() {
  const queryClient = useQueryClient()

  return useMutation<PositionOut, ApiError, PositionIn>({
    mutationFn: addPosition,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: portfolioKeys.all })
    },
  })
}
