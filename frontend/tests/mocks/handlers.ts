import { http, HttpResponse } from 'msw'
import type { HttpHandler } from 'msw'
import type { IBKRStatusResponse } from '../../src/api/ibkr'
import type {
  ClosedTradeOut,
  ClosedTradesResponse,
  FollowUpReviewIn,
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
  BreadthResponse,
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
// GET /api/watchlist/breadth: any tracked (watchlist or portfolio) ticker
// not present in `mockTickerTideTrends` below counts as `unavailable_count`
// (Tide couldn't be computed right now), the same convention as
// mockTickerSignals' own "no entry -> null signal" rule above.
// GET /api/ibkr/status: defaults to 'disabled' (this app's own real
// backend default, `Settings.ibkr_enabled = False`) — every test that
// renders AppShell (frontend-ibkr-status-indicator's IbkrStatusIndicator
// lives in its app bar) hits this handler whether or not it cares about
// IBKR specifically, so the default has to be a fixed, deterministic value.
// A test that does care about a different state (`available`/
// `gateway_unreachable`/`not_authenticated`, or a transport failure)
// overrides it directly with `server.use()`, same as every other
// non-sentinel-driven override in this file (e.g. PriceChart.test.tsx).

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
    trend_strength: { atr: 4.2, plus_di: 28.5, minus_di: 15.3, adx: 22.1 },
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
  // BUY-only (per docs/Analyse.md §7 / the backend-profit-target task) -- non-null here since
  // this fixture's own `signal` is 'BUY'.
  profit_target: {
    price: 245.0,
    source: 'channel',
    distance_to_stop: 9.3,
    distance_to_target: 18.6,
    reward_risk_ratio: 2.0,
    meets_minimum_reward_risk: true,
  },
  extended_data: {
    earnings_date: '2026-10-29',
    earnings_within_warning_days: false,
    ex_dividend_date: '2026-11-15',
    shares_short: 12345678,
    short_ratio: 2.3,
    short_percent_of_float: 0.045,
    float_shares: 1000000000,
    insider_transactions: [],
    unavailable_reason: null,
  },
  insider_clusters: [],
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
        tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
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
        obv: 1250000.0,
        accumulation_distribution: 84210.5,
        trend_strength: { atr: 3.8, plus_di: 26.0, minus_di: 18.5, adx: 20.0 },
      },
      {
        date: '2026-09-02',
        // Matches analysisFixture.screens.tide above -- this is the point that mirrors
        // GET /api/stocks/{ticker}/analysis's own latest-bar snapshot (see this file's other
        // fixtures' shared-latest-bar convention).
        tide: { trend: 'BULLISH', weekly_macd_histogram_slope: 'rising' },
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
        obv: 1450000.0,
        accumulation_distribution: 91500.25,
        trend_strength: { atr: 4.2, plus_di: 28.5, minus_di: 15.3, adx: 22.1 },
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
      trade_letter_grade: 'A',
      follow_up_notes: null,
      follow_up_reviewed_at: null,
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
      trade_letter_grade: null,
      follow_up_notes: null,
      follow_up_reviewed_at: null,
    },
  ],
}

function isoDateWeeksAgo(weeks: number): string {
  const date = new Date()
  date.setUTCDate(date.getUTCDate() - weeks * 7)
  return date.toISOString().slice(0, 10)
}

// A third row dated *relative to now* (unlike the two fixed-date rows
// above), so it reliably falls inside the 8-10-week due-for-follow-up window
// (API.md's `due_for_follow_up` query parameter) regardless of when the test
// suite happens to run -- a fixed date would drift out of the window as real
// time passes. Exercises `POST .../follow-up-review` end to end too: it
// starts unreviewed and, once reviewed, correctly drops out of the
// due-filtered GET (see `isDueForFollowUp` below).
const dueTradeFixture: ClosedTradeOut = {
  id: 'trade_due_nvda',
  ticker: 'NVDA',
  quantity: 10,
  entry_price: 100.0,
  entry_date: isoDateWeeksAgo(12),
  exit_price: 120.0,
  exit_date: isoDateWeeksAgo(9),
  realized_pnl: 200.0,
  exit_reason: 'target_hit',
  buy_grade_pct: null,
  sell_grade_pct: null,
  trade_grade_pct: null,
  trade_letter_grade: null,
  follow_up_notes: null,
  follow_up_reviewed_at: null,
}

// Mutable in-memory closed-trades store backing GET/POST
// /api/portfolio/closed-trades(/*), the same pattern (and reset convention)
// `positions`/`resetPortfolioStore` establish above -- so a test can record a
// follow-up review and then observe it both on a subsequent unfiltered GET
// and dropping out of the due-filtered GET.
type StoredClosedTrade = ClosedTradeOut

const FOLLOW_UP_MIN_WEEKS = 8
const FOLLOW_UP_MAX_WEEKS = 10
const MS_PER_WEEK = 7 * 24 * 60 * 60 * 1000

// Mirrors the backend's own due-for-follow-up filter (API.md,
// backend-trade-journal-followup-review's `decisions` entry): not yet
// reviewed, and `exit_date` between 8 and 10 weeks ago inclusive.
function isDueForFollowUp(trade: StoredClosedTrade): boolean {
  if (trade.follow_up_reviewed_at !== null) {
    return false
  }
  const exitMs = new Date(`${trade.exit_date}T00:00:00Z`).getTime()
  const weeksAgo = (Date.now() - exitMs) / MS_PER_WEEK
  return weeksAgo >= FOLLOW_UP_MIN_WEEKS && weeksAgo <= FOLLOW_UP_MAX_WEEKS
}

function initialClosedTrades(): StoredClosedTrade[] {
  return [...closedTradesFixture.items, dueTradeFixture].map((trade) => ({ ...trade }))
}

let closedTrades: StoredClosedTrade[] = initialClosedTrades()

export function resetClosedTradesStore(): void {
  closedTrades = initialClosedTrades()
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

// Mock Screen 1 (Tide) trend backing GET /api/watchlist/breadth
// (frontend-breadth-widget) — a separate table from mockTickerSignals above
// since a ticker's Tide trend and its overall BUY/SELL/HOLD signal are
// distinct concepts (the latter also depends on Screen 2/3 and Impulse) and
// the real backend's own `_tide_trend` helper is independent of
// `_compute_signal`'s BUY/SELL/HOLD result. One of each trend value, plus a
// ticker deliberately left out (any ticker not present here, e.g. 'ZZZZ' or
// the stocks.ts error-case sentinels) mirrors the real endpoint's
// `unavailable_count` case (Tide couldn't be computed right now) rather
// than needing its own sentinel.
const mockTickerTideTrends: Record<string, 'BULLISH' | 'BEARISH' | 'NEUTRAL'> = {
  AAPL: 'BULLISH',
  MSFT: 'NEUTRAL',
  TSLA: 'BEARISH',
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
  resetClosedTradesStore()
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

const defaultIbkrStatusResponse: IBKRStatusResponse = {
  state: 'disabled',
  detail: 'IBKR integration is disabled (FINTRADE_IBKR_ENABLED is not set).',
}

export const handlers: HttpHandler[] = [
  http.get('/api/ibkr/status', () => HttpResponse.json(defaultIbkrStatusResponse)),

  http.get('/api/portfolio', () => HttpResponse.json(portfolioResponse())),

  http.get('/api/portfolio/risk', () => HttpResponse.json(riskFixture)),

  http.get('/api/portfolio/closed-trades', ({ request }) => {
    const url = new URL(request.url)
    const dueForFollowUp = url.searchParams.get('due_for_follow_up') === 'true'
    const items = dueForFollowUp ? closedTrades.filter(isDueForFollowUp) : closedTrades
    return HttpResponse.json({ items })
  }),

  http.post('/api/portfolio/closed-trades/:trade_id/follow-up-review', async ({
    params,
    request,
  }) => {
    const trade = closedTrades.find((candidate) => candidate.id === params.trade_id)
    if (!trade) {
      return HttpResponse.json({ detail: 'Closed trade not found' }, { status: 404 })
    }
    const body = (await request.json()) as FollowUpReviewIn
    trade.follow_up_notes = body.follow_up_notes
    trade.follow_up_reviewed_at = new Date().toISOString()
    return HttpResponse.json(trade)
  }),

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
      // Mirrors the real backend's merge behavior (see the
      // backend-trade-journal-entry-notes task's `decisions`): an incoming
      // note is appended to the existing one rather than overwriting it; no
      // incoming note leaves the existing one untouched.
      if (body.entry_notes) {
        existing.entry_notes = existing.entry_notes
          ? `${existing.entry_notes}\n\n${body.entry_notes}`
          : body.entry_notes
      }
      stored = existing
    } else {
      stored = {
        id: `pos_${nextPositionId++}`,
        ticker,
        quantity: body.quantity,
        avg_cost_basis: body.avg_cost_basis,
        entry_date: body.entry_date,
        entry_notes: body.entry_notes ?? null,
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

  // GET /api/watchlist/breadth (frontend-breadth-widget): aggregates the
  // union of the in-memory watchlist + portfolio stores' tickers, mirroring
  // the real backend's own dedup-then-count-Tide-trend logic
  // (app.api.routers.watchlist.get_watchlist_breadth) against
  // mockTickerTideTrends above rather than mockTickerSignals (see that
  // table's own comment for why the two are kept separate).
  http.get('/api/watchlist/breadth', () => {
    const trackedTickers = new Set<string>([
      ...watchlistItems.map((item) => item.ticker),
      ...positions.map((position) => position.ticker),
    ])

    let bullishCount = 0
    let bearishCount = 0
    let neutralCount = 0
    let unavailableCount = 0
    for (const ticker of trackedTickers) {
      const trend = mockTickerTideTrends[ticker]
      if (trend === 'BULLISH') {
        bullishCount += 1
      } else if (trend === 'BEARISH') {
        bearishCount += 1
      } else if (trend === 'NEUTRAL') {
        neutralCount += 1
      } else {
        unavailableCount += 1
      }
    }

    const computable = bullishCount + bearishCount + neutralCount
    const pct = (count: number) =>
      computable === 0 ? 0 : Math.round((count / computable) * 1000) / 10

    const response: BreadthResponse = {
      tracked_ticker_count: trackedTickers.size,
      bullish_count: bullishCount,
      bearish_count: bearishCount,
      neutral_count: neutralCount,
      unavailable_count: unavailableCount,
      bullish_pct: pct(bullishCount),
      bearish_pct: pct(bearishCount),
      neutral_pct: pct(neutralCount),
    }
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
