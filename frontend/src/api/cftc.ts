// Typed endpoint function for GET /api/cftc/cot (docs/architecture/API.md),
// mirroring api/homework.ts's shape: one typed function per route, response
// shapes come straight from the generated types.ts.

import { request } from './client'
import type { components } from './types'

export type CFTCCOTResponse = components['schemas']['CFTCCOTResponse']
export type CFTCCOTMarketOut = components['schemas']['CFTCCOTMarketOut']
export type CFTCMarketKey = CFTCCOTMarketOut['market_key']

/**
 * `GET /api/cftc/cot` — current + recent CFTC Commitments of Traders
 * positioning for this app's fixed 5 futures markets (Euro, Yen, Oil, Gold,
 * Bonds; `CFTCCOTResponse.markets`, API.md). Served from a weekly-refreshed
 * DB-backed cache server-side; only rejects (`503`) on a genuine cache-miss
 * live-fetch failure against the CFTC's own data source — see API.md.
 */
export function getCftcCot(): Promise<CFTCCOTResponse> {
  return request<CFTCCOTResponse>('/api/cftc/cot')
}
