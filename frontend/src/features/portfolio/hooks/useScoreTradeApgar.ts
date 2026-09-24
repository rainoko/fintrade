import { useMutation } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { scoreTradeApgar, type TradeApgarIn, type TradeApgarOut } from '../../../api/portfolio'

/**
 * `POST /api/portfolio/trade-apgar` — scores Elder ch. 58's pre-trade "Trade
 * Apgar" go/no-go check (docs/architecture/API.md). A `useMutation` rather
 * than a `useQuery`, even though the endpoint is idempotent/side-effect-free:
 * it's user-triggered ("score this ticker with these manual answers right
 * now"), matching this feature's own established pattern for an on-demand
 * server computation (`useAddPosition`/`useRecordFollowUpReview`) rather than
 * data that benefits from `useQuery`'s cache/staleness semantics — see
 * `frontend-trade-apgar`'s `decisions` entry. No query invalidation: nothing
 * is persisted server-side, so no other query's data can go stale as a
 * result of this call.
 */
export function useScoreTradeApgar() {
  return useMutation<TradeApgarOut, ApiError, TradeApgarIn>({
    mutationFn: scoreTradeApgar,
  })
}
