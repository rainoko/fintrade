import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { getPortfolio, type PortfolioResponse } from '../../../api/portfolio'
import { portfolioKeys } from './queryKeys'

/**
 * `GET /api/portfolio` — current positions plus account equity
 * (docs/architecture/API.md#get-apiportfolio). Typed to `ApiError` (rather
 * than TanStack Query's default `Error`) so callers can pass `.error`
 * straight into `common/ErrorState` without a cast.
 */
export function usePortfolio() {
  return useQuery<PortfolioResponse, ApiError>({
    queryKey: portfolioKeys.all,
    queryFn: getPortfolio,
  })
}
