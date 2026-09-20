// Typed endpoint functions for the /api/stocks/* routes (docs/architecture/API.md).
// Response shapes come straight from the generated types.ts — never redeclared
// by hand — so a backend schema change surfaces here as a compile error the
// next time src/api/types.ts is regenerated.

import { request } from './client'
import type { components } from './types'

export type AnalysisResponse = components['schemas']['AnalysisResponse']
export type HistoryResponse = components['schemas']['HistoryResponse']
export type HistoryInterval = components['schemas']['HistoryResponse']['interval']
export type ConfidenceBreakdownItem = components['schemas']['ConfidenceBreakdownItem']
export type Indicators = components['schemas']['Indicators']
export type TrendStrength = components['schemas']['TrendStrength']
export type Screens = components['schemas']['Screens']
export type TideScreen = components['schemas']['TideScreen']
export type WaveScreen = components['schemas']['WaveScreen']
export type TriggerScreen = components['schemas']['TriggerScreen']
export type IndicatorHistoryResponse = components['schemas']['IndicatorHistoryResponse']
export type IndicatorHistoryPoint = components['schemas']['IndicatorHistoryPoint']
export type SupportResistanceZone = components['schemas']['SupportResistanceZone']
export type FalseBreakoutOut = components['schemas']['FalseBreakoutOut']
export type DivergenceOut = components['schemas']['DivergenceOut']
export type KangarooTailOut = components['schemas']['KangarooTailOut']
export type ProfitTargetOut = components['schemas']['ProfitTargetOut']
export type ExtendedDataOut = components['schemas']['ExtendedDataOut']
export type InsiderTransactionOut = components['schemas']['InsiderTransactionOut']
export type InsiderClusterOut = components['schemas']['InsiderClusterOut']

export interface GetStockHistoryParams {
  /**
   * Lookback window: '<N>d' | '<N>w' | '<N>m' | '<N>y', or 'max' (see
   * API.md). Omitted entirely means the backend's own default ('1y').
   */
  range?: string
  /** Defaults to 'daily' on the backend when omitted. */
  interval?: HistoryInterval
}

/** `GET /api/stocks/{ticker}/analysis` — full Triple Screen evaluation for one ticker. */
export function getStockAnalysis(ticker: string): Promise<AnalysisResponse> {
  return request<AnalysisResponse>(`/api/stocks/${encodeURIComponent(ticker)}/analysis`)
}

/** `GET /api/stocks/{ticker}/history` — raw OHLCV bars for charting. */
export function getStockHistory(
  ticker: string,
  params: GetStockHistoryParams = {},
): Promise<HistoryResponse> {
  const query = new URLSearchParams()
  if (params.range !== undefined) {
    query.set('range', params.range)
  }
  if (params.interval !== undefined) {
    query.set('interval', params.interval)
  }
  const queryString = query.toString()
  const path = `/api/stocks/${encodeURIComponent(ticker)}/history${queryString ? `?${queryString}` : ''}`
  return request<HistoryResponse>(path)
}

export interface GetIndicatorHistoryParams {
  /**
   * Same lookback-window grammar as `GetStockHistoryParams['range']`.
   * Omitted entirely means the backend's own default ('1y').
   */
  range?: string
}

/**
 * `GET /api/stocks/{ticker}/indicators` — historical indicator values and
 * the resulting signal for each daily bar (oldest first), the time-series
 * counterpart to `getStockAnalysis`'s latest-bar-only snapshot. No
 * `interval` param — every value here is daily-cadence (see API.md).
 */
export function getIndicatorHistory(
  ticker: string,
  params: GetIndicatorHistoryParams = {},
): Promise<IndicatorHistoryResponse> {
  const query = new URLSearchParams()
  if (params.range !== undefined) {
    query.set('range', params.range)
  }
  const queryString = query.toString()
  const path = `/api/stocks/${encodeURIComponent(ticker)}/indicators${queryString ? `?${queryString}` : ''}`
  return request<IndicatorHistoryResponse>(path)
}
