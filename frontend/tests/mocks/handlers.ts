import { http, HttpResponse } from 'msw'
import type { HttpHandler } from 'msw'
import type {
  PortfolioResponse,
  PositionIn,
  PositionOut,
  RiskResponse,
} from '../../src/api/portfolio'
import type {
  AnalysisResponse,
  HistoryInterval,
  HistoryResponse,
} from '../../src/api/stocks'

// Handlers mirroring docs/architecture/API.md, including every error case
// listed in API.md's "Error Cases to Cover in Tests" section (see
// Frontend.md's Testing Notes). This is the shared mock layer every later
// feature task's tests reuse — see frontend-api-client's checklist.
//
// Error scenarios are reached through sentinel identifiers (a ticker or
// position id) rather than a separate parallel set of handlers to
// `server.use()` in every consuming test: a test can just request
// `GET /api/stocks/UNKNOWN/analysis` and get the 404 case for free, using
// the exact same handler registration as the happy path. This keeps the
// handler list small and self-documenting, and avoids every feature test
// needing to know MSW's `server.use()` API just to exercise an error case.
//
// Sentinel tickers (case-insensitive, matched after the same uppercase
// normalization the backend applies — see API.md):
//   UNKNOWN       -> 404 (stocks: analysis + history)
//   NOPROVIDER    -> 503 (stocks: analysis + history)
//   THINHISTORY   -> 422 insufficient weekly history (analysis always; history only when interval=weekly)
// Sentinel position ids:
//   any id not present in the in-memory portfolio store -> 404 (DELETE)
// Sentinel POST /api/portfolio/positions payloads:
//   quantity <= 0 or avg_cost_basis <= 0 -> 422 HTTPValidationError (per-field)
//   ticker === 'OVERFLOW'                -> 422 ErrorDetail (merge would overflow)

const analysisFixture: AnalysisResponse = {
  ticker: 'AAPL',
  as_of: '2026-09-11',
  signal: 'BUY',
  confidence: 72,
  confidence_band: 'High',
  screens: {
    tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
    impulse: 'GREEN',
    wave: { stochastic_k: 24.3, force_index_2ema: -18234.5, state: 'OVERSOLD_PULLBACK' },
    trigger: { fired: true, reference: 'close_above_prior_high' },
  },
  confidence_breakdown: [
    { component: 'tide_alignment', weight: 0.3, score: 1.0 },
    { component: 'impulse_gate', weight: 0.2, score: 1.0 },
    { component: 'oscillator_extremity', weight: 0.25, score: 0.6 },
    { component: 'elder_ray_confirmation', weight: 0.15, score: 0.5 },
    { component: 'volume_confirmation', weight: 0.1, score: 1.0 },
  ],
  indicators: {
    ema_13: 226.4,
    ema_26: 221.7,
    macd_histogram: 1.82,
    bull_power: 3.1,
    bear_power: -1.4,
  },
}

function buildHistoryFixture(ticker: string, interval: HistoryInterval): HistoryResponse {
  return {
    ticker,
    interval,
    bars: [
      {
        date: '2026-09-01',
        open: 227.1,
        high: 229.4,
        low: 226.8,
        close: 228.9,
        volume: 51234000,
      },
      {
        date: '2026-09-02',
        open: 228.9,
        high: 230.1,
        low: 227.5,
        close: 229.7,
        volume: 48012000,
      },
    ],
  }
}

const riskFixture: RiskResponse = {
  total_open_risk_pct: 5.4,
  six_percent_rule_breached: false,
  positions: [
    {
      id: 'pos_123',
      ticker: 'AAPL',
      protective_stop: 210.15,
      position_risk_pct: 1.8,
      two_percent_rule_breached: false,
      exit_flags: [],
    },
  ],
}

// Core, always-known fields for a stored position — deliberately excludes
// current_price/unrealized_pnl_pct, which are enriched at *read* time (see
// `enrich` below) rather than stored, mirroring API.md's "price enrichment
// happens on read, not on write" rule: the same stored position can be
// null-priced in a POST response and priced in the following GET.
type StoredPosition = Omit<PositionOut, 'current_price' | 'unrealized_pnl_pct'>

const initialPositions: StoredPosition[] = [
  {
    id: 'pos_123',
    ticker: 'AAPL',
    quantity: 100,
    avg_cost_basis: 195.3,
    entry_date: '2026-05-14',
  },
]

// Mock market prices backing the enrichment above. A ticker with no entry
// here (e.g. a freshly-added position for an unrecognized ticker) enriches
// to a null current_price/unrealized_pnl_pct, the same "price fetch failed"
// case API.md documents for GET /api/portfolio.
const mockPrices: Record<string, number> = { AAPL: 228.9, MSFT: 410.5 }

function enrich(position: StoredPosition): PositionOut {
  const price = mockPrices[position.ticker] ?? null
  const unrealizedPnlPct =
    price === null
      ? null
      : ((price - position.avg_cost_basis) / position.avg_cost_basis) * 100
  return { ...position, current_price: price, unrealized_pnl_pct: unrealizedPnlPct }
}

// Mutable in-memory portfolio store backing GET/POST/DELETE
// /api/portfolio/positions so a test can add/delete a position and then
// observe the effect on a subsequent GET /api/portfolio — mirroring how the
// real backend persists across requests within one session. `resetPortfolioStore`
// puts it back to `initialPositions` between tests (call from `beforeEach`);
// `tests/setup.ts`'s `server.resetHandlers()` alone does not reset this,
// since it's module-level state, not a handler registration.
let positions: StoredPosition[] = initialPositions.map((position) => ({ ...position }))
let nextPositionId = 1

export function resetPortfolioStore(): void {
  positions = initialPositions.map((position) => ({ ...position }))
  nextPositionId = 1
}

function cash(): number {
  return 5000.0
}

function positionsValue(): number {
  // A position with no known price contributes nothing to positions_value
  // rather than falling back to cost basis (API.md's degrade-gracefully rule).
  return positions.reduce(
    (sum, position) => sum + (mockPrices[position.ticker] ?? 0) * position.quantity,
    0,
  )
}

function portfolioResponse(): PortfolioResponse {
  const value = positionsValue()
  return {
    equity: { cash: cash(), positions_value: value, total: cash() + value },
    positions: positions.map(enrich),
  }
}

const MIN_WEEKLY_BARS_TICKER = 'THINHISTORY'
const UNKNOWN_TICKER = 'UNKNOWN'
const PROVIDER_DOWN_TICKER = 'NOPROVIDER'

const RANGE_PATTERN = /^(max|\d{1,4}[dwmy])$/

export const handlers: HttpHandler[] = [
  http.get('/api/portfolio', () => HttpResponse.json(portfolioResponse())),

  http.get('/api/portfolio/risk', () => HttpResponse.json(riskFixture)),

  http.post('/api/portfolio/positions', async ({ request }) => {
    const body = (await request.json()) as PositionIn

    if (body.quantity <= 0 || body.avg_cost_basis <= 0) {
      return HttpResponse.json(
        {
          detail: [
            {
              loc: ['body', body.quantity <= 0 ? 'quantity' : 'avg_cost_basis'],
              msg: 'Input should be greater than 0',
              type: 'greater_than',
            },
          ],
        },
        { status: 422 },
      )
    }

    if (body.ticker.toUpperCase() === 'OVERFLOW') {
      return HttpResponse.json(
        { detail: 'Merging this position would produce a value too large to represent.' },
        { status: 422 },
      )
    }

    const ticker = body.ticker.trim().toUpperCase()
    const existing = positions.find((position) => position.ticker === ticker)

    let stored: StoredPosition
    if (existing) {
      const totalQuantity = existing.quantity + body.quantity
      const blendedCostBasis =
        (existing.quantity * existing.avg_cost_basis +
          body.quantity * body.avg_cost_basis) /
        totalQuantity
      existing.quantity = totalQuantity
      existing.avg_cost_basis = blendedCostBasis
      existing.entry_date =
        existing.entry_date < body.entry_date ? existing.entry_date : body.entry_date
      stored = existing
    } else {
      stored = {
        id: `pos_${nextPositionId++}`,
        ticker,
        quantity: body.quantity,
        avg_cost_basis: body.avg_cost_basis,
        entry_date: body.entry_date,
      }
      positions.push(stored)
    }

    // current_price/unrealized_pnl_pct are always null in the POST response
    // itself (API.md) even though a subsequent GET /api/portfolio enriches
    // this same stored position from mockPrices — see `enrich` above.
    const created: PositionOut = {
      ...stored,
      current_price: null,
      unrealized_pnl_pct: null,
    }
    return HttpResponse.json(created, { status: 201 })
  }),

  http.delete('/api/portfolio/positions/:id', ({ params }) => {
    const { id } = params
    const index = positions.findIndex((position) => position.id === id)
    if (index === -1) {
      return HttpResponse.json({ detail: 'Position not found' }, { status: 404 })
    }
    positions.splice(index, 1)
    return new HttpResponse(null, { status: 204 })
  }),

  http.get('/api/stocks/:ticker/analysis', ({ params }) => {
    const ticker = String(params.ticker).toUpperCase()

    if (ticker === UNKNOWN_TICKER) {
      return HttpResponse.json({ detail: `Unknown ticker: ${ticker}` }, { status: 404 })
    }
    if (ticker === PROVIDER_DOWN_TICKER) {
      return HttpResponse.json(
        { detail: 'Market data provider is currently unavailable. Try again shortly.' },
        { status: 503 },
      )
    }
    if (ticker === MIN_WEEKLY_BARS_TICKER) {
      return HttpResponse.json(
        {
          detail: `Insufficient weekly history for ${ticker} to compute weekly indicators (< 26 weeks).`,
        },
        { status: 422 },
      )
    }

    return HttpResponse.json({ ...analysisFixture, ticker })
  }),

  http.get('/api/stocks/:ticker/history', ({ params, request }) => {
    const ticker = String(params.ticker).toUpperCase()
    const url = new URL(request.url)
    const range = url.searchParams.get('range') ?? '1y'
    const interval = (url.searchParams.get('interval') ?? 'daily') as HistoryInterval

    if (!RANGE_PATTERN.test(range)) {
      return HttpResponse.json(
        {
          detail: [
            {
              loc: ['query', 'range'],
              msg: "String should match pattern '^(max|\\d{1,4}[dwmy])$'",
              type: 'string_pattern_mismatch',
            },
          ],
        },
        { status: 422 },
      )
    }
    if (ticker === UNKNOWN_TICKER) {
      return HttpResponse.json({ detail: `Unknown ticker: ${ticker}` }, { status: 404 })
    }
    if (ticker === PROVIDER_DOWN_TICKER) {
      return HttpResponse.json(
        { detail: 'Market data provider is currently unavailable. Try again shortly.' },
        { status: 503 },
      )
    }
    if (ticker === MIN_WEEKLY_BARS_TICKER && interval === 'weekly') {
      return HttpResponse.json(
        { detail: `Insufficient weekly history for ${ticker} (< 26 weeks).` },
        { status: 422 },
      )
    }

    return HttpResponse.json(buildHistoryFixture(ticker, interval))
  }),
]
