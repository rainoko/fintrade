import { http, HttpResponse } from 'msw'
import type { HttpHandler } from 'msw'
import type {
  ClosedTradesResponse,
  PortfolioResponse,
  PositionIn,
  PositionOut,
  RiskResponse,
} from '../../src/api/portfolio'
import type {
  AnalysisResponse,
  HistoryInterval,
  HistoryResponse,
  IndicatorHistoryResponse,
} from '../../src/api/stocks'
import type {
  WatchlistItemIn,
  WatchlistItemOut,
  WatchlistResponse,
} from '../../src/api/watchlist'

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
//   UNKNOWN       -> 404 (stocks: analysis + history + indicators)
//   NOPROVIDER    -> 503 (stocks: analysis + history + indicators)
//   THINHISTORY   -> 422 insufficient weekly history (analysis + indicators always; history only when interval=weekly)
// Sentinel position ids:
//   any id not present in the in-memory portfolio store -> 404 (DELETE)
// Sentinel POST /api/portfolio/positions payloads:
//   quantity <= 0 or avg_cost_basis <= 0 -> 422 HTTPValidationError (per-field)
//   ticker === 'OVERFLOW'                -> 422 ErrorDetail (merge would overflow)
// Watchlist/portfolio tickers: any ticker not present in `mockTickerSignals`
// below annotates as signal/confidence/confidence_band all null on both GET
// /api/watchlist and GET /api/portfolio (API.md's nullable-on-failure case)
// rather than needing its own sentinel — this mirrors mockPrices' "unknown
// ticker -> null price" convention above.
// Sentinel watchlist tickers:
//   any ticker not present in the in-memory watchlist store -> 404 (DELETE)

const analysisFixture: AnalysisResponse = {
  ticker: 'AAPL',
  as_of: '2026-09-11',
  signal: 'BUY',
  confidence: 72,
  confidence_band: 'High',
  screens: {
    tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
    impulse: 'GREEN',
    wave: {
      stochastic_k: 24.3,
      force_index_2ema: -18234.5,
      state: 'OVERSOLD_PULLBACK',
      showed_pullback_in_lookback: true,
      showed_rally_in_lookback: false,
    },
    trigger: { fired: true, reference: 'close_above_prior_high' },
  },
  confidence_breakdown: [
    { component: 'tide_alignment', weight: 0.3, score: 1.0 },
    { component: 'impulse_gate', weight: 0.2, score: 1.0 },
    { component: 'oscillator_extremity', weight: 0.25, score: 0.6 },
    { component: 'elder_ray_confirmation', weight: 0.15, score: 0.5 },
    { component: 'volume_confirmation', weight: 0.1, score: 1.0 },
  ],
  divergence: null,
  kangaroo_tail: null,
  indicators: {
    ema_13: 226.4,
    ema_26: 221.7,
    macd_histogram: 1.82,
    bull_power: 3.1,
    bear_power: -1.4,
  },
  support_resistance_zones: [
    {
      role: 'resistance',
      upper: 236.9,
      lower: 233.4,
      first_touch_date: '2026-06-02',
      last_touch_date: '2026-08-14',
      touch_count: 3,
      length_days: 73,
      length_category: 'intermediate',
      height_pct: 1.5,
      height_category: 'minor',
      dollar_volume: 12_400_000_000,
      strength_score: 50,
      broken: false,
      break_date: null,
      false_breakout: null,
    },
  ],
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

// One HOLD point followed by a BUY point, matching the two dates in
// buildHistoryFixture above — enough for a consuming test to see the
// "signal transitioned into BUY" marker case (frontend-chart-signal-overlay)
// without every point sharing one signal.
function buildIndicatorHistoryFixture(ticker: string): IndicatorHistoryResponse {
  return {
    ticker,
    points: [
      {
        date: '2026-09-01',
        ema_13: 225.1,
        ema_26: 220.4,
        macd_histogram: 1.2,
        bull_power: 2.5,
        bear_power: -1.1,
        stochastic_k: 55.0,
        force_index_2ema: 1000.0,
        signal: 'HOLD',
        confidence: 0,
        confidence_band: 'Low',
      },
      {
        date: '2026-09-02',
        ema_13: 226.4,
        ema_26: 221.7,
        macd_histogram: 1.82,
        bull_power: 3.1,
        bear_power: -1.4,
        stochastic_k: 24.3,
        force_index_2ema: -18234.5,
        signal: 'BUY',
        confidence: 72,
        confidence_band: 'High',
      },
    ],
  }
}

// Hand-checked against docs/Analyse.md §7's own worked ADSK example (buy
// grade 97%, sell grade 35%, trade grade 32% -- backend/tests/unit/
// test_portfolio_grading.py verifies these exact formulas server-side; this
// fixture just reuses the same numbers so a frontend test can assert on a
// value it can cross-check against the doc directly). The second row
// (`trade_null`) exercises API.md's documented null-grade case (entry date
// predates the ticker's fetchable history / falls inside the Autoenvelope's
// warm-up window) -- grading never fails the request, so the row itself
// stays fully populated with only its three grade fields null.
const closedTradesFixture: ClosedTradesResponse = {
  items: [
    {
      id: 'trade_abc123',
      ticker: 'ADSK',
      quantity: 100,
      entry_price: 51.77,
      entry_date: '2026-03-02',
      exit_price: 53.78,
      exit_date: '2026-03-09',
      realized_pnl: 201.0,
      exit_reason: 'target_hit',
      buy_grade_pct: 97.3,
      sell_grade_pct: 35.5,
      trade_grade_pct: 32.1,
    },
    {
      id: 'trade_def456',
      ticker: 'TSLA',
      quantity: 5,
      entry_price: 210.0,
      entry_date: '2026-01-15',
      exit_price: 195.0,
      exit_date: '2026-01-22',
      realized_pnl: -75.0,
      exit_reason: 'stop_hit',
      buy_grade_pct: null,
      sell_grade_pct: null,
      trade_grade_pct: null,
    },
  ],
}

const riskFixture: RiskResponse = {
  total_open_risk_pct: 5.4,
  realized_losses_this_month_pct: 0,
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

// Mock signal/confidence backing both GET /api/watchlist's and GET
// /api/portfolio's per-ticker annotation (the real backend re-runs
// app.signals.engine.analyse per ticker for each; this mock layer never
// re-implements that — it just returns canned per-ticker results, shared
// between both endpoints since api-portfolio-position-signal's decisions
// establish GET /api/portfolio reuses the exact same signal engine GET
// /api/watchlist does, not a second computation). A ticker with no entry
// here annotates as signal/confidence/confidence_band all null, the same
// "signal couldn't be computed" case API.md documents. Includes one of each
// signal value so a test can assert BUY renders visually distinct from
// HOLD/SELL.
const mockTickerSignals: Record<
  string,
  Pick<WatchlistItemOut, 'signal' | 'confidence' | 'confidence_band'>
> = {
  AAPL: { signal: 'BUY', confidence: 72, confidence_band: 'High' },
  MSFT: { signal: 'HOLD', confidence: 45, confidence_band: 'Medium' },
  TSLA: { signal: 'SELL', confidence: 30, confidence_band: 'Low' },
}

// Core, always-known fields for a stored position — deliberately excludes
// current_price/unrealized_pnl_pct/signal/confidence/confidence_band, which
// are enriched at *read* time (see `enrich` below) rather than stored,
// mirroring API.md's "enrichment happens on read, not on write" rule: the
// same stored position can be null-priced/null-signaled in a POST response
// and populated in the following GET.
type StoredPosition = Omit<
  PositionOut,
  'current_price' | 'unrealized_pnl_pct' | 'signal' | 'confidence' | 'confidence_band'
>

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
  // Reuses the same mockTickerSignals canned-signal table GET /api/watchlist
  // draws from (frontend-lists-show-signal) rather than a second one — the
  // real backend annotates both endpoints from the same signal engine
  // (api-portfolio-position-signal's decisions). A ticker with no entry
  // annotates as signal/confidence/confidence_band all null, the same
  // "signal couldn't be computed" case API.md documents.
  const signalData = mockTickerSignals[position.ticker]
  return {
    ...position,
    current_price: price,
    unrealized_pnl_pct: unrealizedPnlPct,
    signal: signalData?.signal ?? null,
    confidence: signalData?.confidence ?? null,
    confidence_band: signalData?.confidence_band ?? null,
  }
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

// Core, always-known fields for a stored watchlist item — deliberately
// excludes signal/confidence/confidence_band, which are annotated at *read*
// time (see `enrichWatchlistItem` below) rather than stored, mirroring
// StoredPosition's same "enrichment happens on read, not on write" pattern
// above for current_price/unrealized_pnl_pct.
type StoredWatchlistItem = Pick<WatchlistItemOut, 'ticker' | 'added_at'>

const initialWatchlistItems: StoredWatchlistItem[] = [
  { ticker: 'AAPL', added_at: '2026-09-10T09:15:00Z' },
  { ticker: 'MSFT', added_at: '2026-09-12T09:15:00Z' },
]

function enrichWatchlistItem(item: StoredWatchlistItem): WatchlistItemOut {
  const signalData = mockTickerSignals[item.ticker]
  return {
    ...item,
    signal: signalData?.signal ?? null,
    confidence: signalData?.confidence ?? null,
    confidence_band: signalData?.confidence_band ?? null,
  }
}

// Mutable in-memory watchlist store backing GET/POST/DELETE /api/watchlist,
// the same pattern (and reset convention) `positions`/`resetPortfolioStore`
// establish above. `resetWatchlistStore` puts it back to
// `initialWatchlistItems` between tests (call from `beforeEach`).
let watchlistItems: StoredWatchlistItem[] = initialWatchlistItems.map((item) => ({
  ...item,
}))

export function resetWatchlistStore(): void {
  watchlistItems = initialWatchlistItems.map((item) => ({ ...item }))
}

export const handlers: HttpHandler[] = [
  http.get('/api/portfolio', () => HttpResponse.json(portfolioResponse())),

  http.get('/api/portfolio/risk', () => HttpResponse.json(riskFixture)),

  http.get('/api/portfolio/closed-trades', () => HttpResponse.json(closedTradesFixture)),

  http.post('/api/portfolio/positions', async ({ request }) => {
    const body = (await request.json()) as PositionIn

    if (body.quantity <= 0 || body.avg_cost_basis <= 0) {
      const detail = []
      if (body.quantity <= 0) {
        detail.push({
          loc: ['body', 'quantity'],
          msg: 'Input should be greater than 0',
          type: 'greater_than',
        })
      }
      if (body.avg_cost_basis <= 0) {
        detail.push({
          loc: ['body', 'avg_cost_basis'],
          msg: 'Input should be greater than 0',
          type: 'greater_than',
        })
      }
      return HttpResponse.json({ detail }, { status: 422 })
    }

    if (body.ticker.trim().toUpperCase() === 'OVERFLOW') {
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

    // current_price/unrealized_pnl_pct/signal/confidence/confidence_band are
    // always null in the POST response itself (API.md) even though a
    // subsequent GET /api/portfolio enriches this same stored position from
    // mockPrices/mockTickerSignals — see `enrich` above.
    const created: PositionOut = {
      ...stored,
      current_price: null,
      unrealized_pnl_pct: null,
      signal: null,
      confidence: null,
      confidence_band: null,
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

  http.get('/api/stocks/:ticker/indicators', ({ params, request }) => {
    const ticker = String(params.ticker).toUpperCase()
    const url = new URL(request.url)
    const range = url.searchParams.get('range') ?? '1y'

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
    if (ticker === MIN_WEEKLY_BARS_TICKER) {
      return HttpResponse.json(
        {
          detail: `Insufficient weekly history for ${ticker} to compute weekly indicators (< 26 weeks).`,
        },
        { status: 422 },
      )
    }

    return HttpResponse.json(buildIndicatorHistoryFixture(ticker))
  }),

  http.get('/api/watchlist', () => {
    const response: WatchlistResponse = { items: watchlistItems.map(enrichWatchlistItem) }
    return HttpResponse.json(response)
  }),

  http.post('/api/watchlist', async ({ request }) => {
    const body = (await request.json()) as WatchlistItemIn
    const ticker = body.ticker.trim().toUpperCase()
    const existing = watchlistItems.find((item) => item.ticker === ticker)

    // Idempotent no-op on a duplicate add (API.md): the existing item, with
    // its original added_at, is returned unchanged rather than a new row
    // being created or added_at being reset to "now".
    const stored = existing ?? { ticker, added_at: new Date().toISOString() }
    if (!existing) {
      watchlistItems.push(stored)
    }

    // signal/confidence/confidence_band are always null in the POST
    // response itself (API.md) — annotation happens on read, not on write.
    const created: WatchlistItemOut = {
      ticker: stored.ticker,
      added_at: stored.added_at,
      signal: null,
      confidence: null,
      confidence_band: null,
    }
    return HttpResponse.json(created, { status: 201 })
  }),

  http.delete('/api/watchlist/:ticker', ({ params }) => {
    const ticker = String(params.ticker).toUpperCase()
    const index = watchlistItems.findIndex((item) => item.ticker === ticker)
    if (index === -1) {
      return HttpResponse.json(
        { detail: `${ticker} is not on the watchlist.` },
        { status: 404 },
      )
    }
    watchlistItems.splice(index, 1)
    return new HttpResponse(null, { status: 204 })
  }),
]
