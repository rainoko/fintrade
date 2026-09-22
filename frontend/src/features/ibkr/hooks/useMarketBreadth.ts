import { useQuery } from '@tanstack/react-query'
import { ApiError } from '../../../api/client'
import {
  recordIbkrBreadthSnapshot,
  type IBKRBreadthSnapshotRequest,
  type IBKRBreadthSnapshotResponse,
} from '../../../api/ibkr'
import { ibkrKeys } from './queryKeys'

/**
 * The two fixed `POST /api/ibkr/breadth/snapshot` requests this widget
 * composes into an Advance/Decline-style reading (Elder ch. 34-36,
 * docs/Analyse.md's "IBKR-scanner breadth approximation" section):
 * `TOP_PERC_GAIN`/`TOP_PERC_LOSE` as a top-gainers-vs-top-losers proxy for
 * advancers vs. decliners — the exact pairing docs/Analyse.md's own text
 * names as an example ("top-gainers vs. top-losers for an Advance/Decline
 * reading"). This app deliberately never hardcodes which IBKR scan-type
 * code means "new highs" vs. "new lows" (unconfirmed against a live
 * gateway, per `backend-market-breadth-indicators`'s own `decisions`
 * entry) — picking a category *pairing* to display by default is a
 * different, smaller commitment than that: worst case, if `TOP_PERC_GAIN`/
 * `TOP_PERC_LOSE` turn out not to be real category codes once tested
 * against a live gateway, `IBKRProvider.run_scanner` simply returns a
 * transient failure surfaced as this widget's own `ErrorState` — never a
 * silently wrong number — the same fail-safe every other IBKR-backed
 * feature in this app already relies on. See this task's `decisions`
 * entry for the full reasoning, including why a live category-picker (the
 * `frontend-market-scanner-page` task's own future scope) isn't built here
 * too.
 */
export const ADVANCE_SNAPSHOT_REQUEST: IBKRBreadthSnapshotRequest = {
  series_key: 'adv',
  scan_config: { instrument: 'STK', type: 'TOP_PERC_GAIN', location: 'STK.US.MAJOR' },
}

export const DECLINE_SNAPSHOT_REQUEST: IBKRBreadthSnapshotRequest = {
  series_key: 'dec',
  scan_config: { instrument: 'STK', type: 'TOP_PERC_LOSE', location: 'STK.US.MAJOR' },
}

export interface MarketBreadthData {
  advance: IBKRBreadthSnapshotResponse
  decline: IBKRBreadthSnapshotResponse
}

/**
 * Fetches one snapshot, retrying exactly once after `Retry-After` on a
 * `429` (`IBKRProvider.run_scanner`'s own 1-request/second client-side
 * throttle) rather than surfacing it as an immediate error — see
 * `fetchMarketBreadth` below for why this matters for the *second* of the
 * two sequential requests it makes.
 */
async function fetchSnapshotWithRateLimitRetry(
  body: IBKRBreadthSnapshotRequest,
): Promise<IBKRBreadthSnapshotResponse> {
  try {
    return await recordIbkrBreadthSnapshot(body)
  } catch (error) {
    if (error instanceof ApiError && error.status === 429 && error.retryAfterSeconds !== null) {
      const retryAfterMs = error.retryAfterSeconds * 1000
      await new Promise((resolve) => setTimeout(resolve, retryAfterMs))
      return recordIbkrBreadthSnapshot(body)
    }
    throw error
  }
}

/**
 * Fetches the advance and decline snapshots sequentially, never
 * concurrently: `IBKRProvider.run_scanner`'s 1-request/second throttle is
 * enforced instance-wide on the backend's process-level singleton, so two
 * same-day-cache-miss requests fired in parallel (the first time ever, or
 * the first load of a new calendar day) would very likely have the second
 * one rejected with `429`. Awaiting the first before starting the second
 * — plus the retry-after-`Retry-After` fallback above for the rare case
 * they're still less than a second apart — means this only ever needs a
 * second real network round trip on that same rare first-load-of-the-day
 * case; every other load is two fast cache hits.
 */
async function fetchMarketBreadth(): Promise<MarketBreadthData> {
  const advance = await fetchSnapshotWithRateLimitRetry(ADVANCE_SNAPSHOT_REQUEST)
  const decline = await fetchSnapshotWithRateLimitRetry(DECLINE_SNAPSHOT_REQUEST)
  return { advance, decline }
}

/**
 * `POST /api/ibkr/breadth/snapshot` x2, composed into one Advance/Decline-
 * style reading (docs/architecture/API.md, docs/Analyse.md's "IBKR-scanner
 * breadth approximation" section). A `useQuery` despite the underlying
 * calls being POSTs: this is an auto-fetch-on-mount, cacheable-per-day read
 * (the backend itself caches by calendar day), the same "benefits from
 * useQuery's cache/staleness semantics" shape `useWatchlistBreadth`/
 * `usePortfolioRisk` already have — not a user-triggered on-demand
 * computation like `useScoreTradeApgar`'s own `useMutation` (see that
 * hook's doc comment for the contrasting case).
 */
export function useMarketBreadth() {
  return useQuery<MarketBreadthData, ApiError>({
    queryKey: ibkrKeys.breadthAdvanceDecline,
    queryFn: fetchMarketBreadth,
  })
}
