import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { getIbkrStatus, type IBKRStatusResponse } from '../../../api/ibkr'
import { ibkrKeys } from './queryKeys'

/**
 * `GET /api/ibkr/status` — whether the optional IBKR Client Portal Gateway
 * integration is usable right now
 * (docs/architecture/API.md#get-apiibkrstatus). Typed to `ApiError` (rather
 * than TanStack Query's default `Error`), same as every other query hook in
 * this app.
 *
 * `isError` here only ever reflects a genuine transport-level failure (this
 * app's own backend being unreachable) — the endpoint's own contract is to
 * never fail for any gateway state, so `disabled`/`available`/
 * `gateway_unreachable`/`not_authenticated` all arrive as ordinary `data`.
 * `IbkrStatusIndicator` renders that transport failure distinctly from any
 * of the four real states, rather than folding it into one of them.
 *
 * `refetchInterval: 30_000`, unlike this app's usual "fetch once, refetch on
 * next mount/invalidate" query hooks: this value can change with nothing
 * this app's own UI did to cause it (the gateway process going down, or an
 * IBKR browser-login session quietly expiring in the background —
 * docs/ideas.md's IBKR follow-ups section), and the component that renders
 * it (`IbkrStatusIndicator`) mounts once in `AppShell` for the whole session
 * rather than remounting per page — without its own poll it would never
 * notice either change. See this task's `decisions` entry.
 */
export function useIbkrStatus() {
  return useQuery<IBKRStatusResponse, ApiError>({
    queryKey: ibkrKeys.status,
    queryFn: getIbkrStatus,
    refetchInterval: 30_000,
  })
}
