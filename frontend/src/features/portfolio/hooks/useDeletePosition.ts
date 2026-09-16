import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { deletePosition } from '../../../api/portfolio'
import { portfolioKeys } from './queryKeys'

/**
 * `DELETE /api/portfolio/positions/{id}` — removes a position entirely
 * (docs/architecture/API.md#delete-apiportfoliopositionsid). Invalidates the
 * portfolio query (and, via prefix-matching, the portfolio-risk query — see
 * queryKeys.ts) so the removed position and its contribution to equity/risk
 * disappear immediately rather than lingering until an unrelated refetch.
 */
export function useDeletePosition() {
  const queryClient = useQueryClient()

  return useMutation<void, ApiError, string>({
    mutationFn: (id: string) => deletePosition(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: portfolioKeys.all })
    },
  })
}
