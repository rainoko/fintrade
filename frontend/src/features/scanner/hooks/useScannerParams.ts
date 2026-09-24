import { useQuery } from '@tanstack/react-query'
import type { ApiError } from '../../../api/client'
import { getIbkrScannerParams, type IBKRScannerParamsResponse } from '../../../api/ibkr'
import { scannerKeys } from './queryKeys'

/**
 * `GET /api/ibkr/scanner/params` — IBKR's own predefined scan categories, or
 * the reason the scanner is currently unavailable
 * (docs/architecture/API.md#get-apiibkrscannerparams). Typed to `ApiError`
 * (rather than TanStack Query's default `Error`) so ScannerPage can pass
 * `.error` straight into `common/ErrorState` without a cast — this only
 * fires for a genuine transport/`503` failure; `disabled`/
 * `gateway_unreachable`/`not_authenticated` are ordinary `200` responses
 * read off `.data.state` instead (see `common/UnavailableState`).
 */
export function useScannerParams() {
  return useQuery<IBKRScannerParamsResponse, ApiError>({
    queryKey: scannerKeys.params,
    queryFn: getIbkrScannerParams,
  })
}
