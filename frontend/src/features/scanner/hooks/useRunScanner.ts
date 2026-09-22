import { useMutation } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import {
  runIbkrScanner,
  type IBKRScannerRunRequest,
  type IBKRScannerRunResponse,
} from '../../../api/ibkr'
import { scannerKeys } from './queryKeys'

/**
 * `POST /api/ibkr/scanner/run` — runs one scan and returns its candidate
 * list, or the reason the scanner is currently unavailable
 * (docs/architecture/API.md#post-apiibkrscannerrun). No cache to invalidate
 * on success (see `scannerKeys.run`'s own doc comment) — a scan result is
 * this mutation's own returned `data`, not a query any other component
 * reads. Rejects with a typed `ApiError` for `429` (rate-limited, surfaced
 * via `ApiError.retryAfterSeconds`) or `503` (a transient scan-call
 * failure); `disabled`/`gateway_unreachable`/`not_authenticated` resolve
 * normally with `.data.state` set instead, same convention as
 * `useScannerParams`.
 */
export function useRunScanner() {
  return useMutation<IBKRScannerRunResponse, ApiError, IBKRScannerRunRequest>({
    mutationKey: scannerKeys.run,
    mutationFn: runIbkrScanner,
  })
}
