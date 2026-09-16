// Typed endpoint functions for the /api/portfolio/* routes (docs/architecture/API.md).
// Response/request shapes come straight from the generated types.ts.

import { request } from './client'
import type { components } from './types'

export type PortfolioResponse = components['schemas']['PortfolioResponse']
export type RiskResponse = components['schemas']['RiskResponse']
export type RiskPosition = components['schemas']['RiskPosition']
export type PositionIn = components['schemas']['PositionIn']
export type PositionOut = components['schemas']['PositionOut']

/** `GET /api/portfolio` — current positions plus account equity. */
export function getPortfolio(): Promise<PortfolioResponse> {
  return request<PortfolioResponse>('/api/portfolio')
}

/** `GET /api/portfolio/risk` — portfolio-level 2%/6% rule evaluation (Analyse.md §7). */
export function getPortfolioRisk(): Promise<RiskResponse> {
  return request<RiskResponse>('/api/portfolio/risk')
}

/**
 * `POST /api/portfolio/positions` — add a position. Adding a ticker that's
 * already held merges into the existing position (quantity-weighted average
 * cost basis) rather than creating a duplicate row — see API.md.
 */
export function addPosition(payload: PositionIn): Promise<PositionOut> {
  return request<PositionOut>('/api/portfolio/positions', {
    method: 'POST',
    body: payload,
  })
}

/** `DELETE /api/portfolio/positions/{id}` — removes a position entirely. */
export function deletePosition(id: string): Promise<void> {
  return request<void>(`/api/portfolio/positions/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
}
