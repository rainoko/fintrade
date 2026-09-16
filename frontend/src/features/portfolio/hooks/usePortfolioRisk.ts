import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { getPortfolioRisk, type RiskResponse } from '../../../api/portfolio'
import { portfolioKeys } from './queryKeys'

/**
 * `GET /api/portfolio/risk` — portfolio-level 2%/6% rule evaluation
 * (docs/architecture/API.md#get-apiportfoliorisk, docs/Analyse.md §7). Typed
 * to `ApiError` (rather than TanStack Query's default `Error`) so callers
 * can pass `.error` straight into `common/ErrorState` without a cast, same
 * as usePortfolio.
 */
export function usePortfolioRisk() {
  return useQuery<RiskResponse, ApiError>({
    queryKey: portfolioKeys.risk,
    queryFn: getPortfolioRisk,
  })
}
