# API Contract

REST/JSON, served by the FastAPI backend (see [Backend.md](Backend.md)), consumed by the React frontend (see [Frontend.md](Frontend.md)). This document is the human-readable contract; the FastAPI app's auto-generated OpenAPI schema is the machine-readable source of truth frontend types should be generated from.

## Conventions

- All responses are JSON. Timestamps are ISO 8601 UTC.
- Errors follow `{ "detail": string }` (FastAPI default) with an appropriate HTTP status code.
- Money/price values are numbers (floats), not strings.
- Endpoints are versionless for MVP (`/api/...`, no `/v1/`) — add versioning if/when a breaking change is needed post-launch.

## Endpoints

### `GET /api/stocks/{ticker}/history`

Daily OHLCV history for charting.

Query params: `range` (`<N>d` | `<N>w` | `<N>m` | `<N>y` | `max`, e.g. `1y`, `6m`, `90d`; default `1y`), `interval` (`daily` | `weekly`, default `daily`). `range` is a trailing window measured back from the most recent bar actually returned (not from today's date, since the cache can be stale and a delisted/thinly-traded ticker's history may not reach the present) — an unrecognized `range` value is a `422`.

```json
{
  "ticker": "AAPL",
  "interval": "daily",
  "bars": [
    { "date": "2026-09-01", "open": 227.1, "high": 229.4, "low": 226.8, "close": 228.9, "volume": 51234000 }
  ]
}
```

### `GET /api/stocks/{ticker}/analysis`

Full Triple Screen evaluation for one ticker — signal, confidence, and the breakdown behind it.

```json
{
  "ticker": "AAPL",
  "as_of": "2026-09-11",
  "signal": "BUY",
  "confidence": 72,
  "confidence_band": "High",
  "screens": {
    "tide": { "trend": "BULLISH", "weekly_macd_histogram_slope": "rising" },
    "impulse": "GREEN",
    "wave": { "stochastic_k": 24.3, "force_index_2ema": -18234.5, "state": "OVERSOLD_PULLBACK" },
    "trigger": { "fired": true, "reference": "close_above_prior_high" }
  },
  "confidence_breakdown": [
    { "component": "tide_alignment", "weight": 0.30, "score": 1.0 },
    { "component": "impulse_gate", "weight": 0.20, "score": 1.0 },
    { "component": "oscillator_extremity", "weight": 0.25, "score": 0.6 },
    { "component": "elder_ray_confirmation", "weight": 0.15, "score": 0.5 },
    { "component": "volume_confirmation", "weight": 0.10, "score": 1.0 }
  ],
  "indicators": {
    "ema_13": 226.4,
    "ema_26": 221.7,
    "macd_histogram": 1.82,
    "bull_power": 3.1,
    "bear_power": -1.4
  }
}
```

`signal` ∈ `BUY | SELL | HOLD`. `confidence` is an integer 0–100. `confidence_band` ∈ `Low | Medium | High` per Analyse.md §6.

### `GET /api/stocks/{ticker}/indicators`

Historical indicator values and the resulting signal for each daily bar — the time-series counterpart to `/analysis`'s latest-bar-only snapshot, for charting an indicator overlay (Analyse.md §4-5).

Query params: `range` (same grammar as `/history`'s `range` — `<N>d` | `<N>w` | `<N>m` | `<N>y` | `max`, default `1y`). Daily bars only — no `interval` param, since every indicator/Screen this endpoint computes is itself daily-cadence.

```json
{
  "ticker": "AAPL",
  "points": [
    {
      "date": "2026-09-11",
      "ema_13": 226.4,
      "ema_26": 221.7,
      "macd_histogram": 1.82,
      "bull_power": 3.1,
      "bear_power": -1.4,
      "stochastic_k": 24.3,
      "force_index_2ema": -18234.5,
      "signal": "BUY",
      "confidence": 72,
      "confidence_band": "High"
    }
  ]
}
```

`points` is oldest-first, one entry per daily bar in the requested range, produced by re-running the signal engine (`app.signals.engine.analyse`) once per bar using only that bar's own history — including Screen 1 (Tide), which is recomputed from only the weekly bars as-of that day's own calendar week (`app.signals.engine._weekly_through_bar_date`), not held fixed at today's value — so `signal`/`confidence`/Tide all genuinely vary day to day, not just the underlying daily indicators, with no look-ahead. The last entry always matches `GET /api/stocks/{ticker}/analysis` for the same ticker at the same date: for the most recent daily bar, "the weekly bars as-of that bar's calendar week" naturally reduces to the full weekly series `/analysis` itself uses — see the `api-stocks-indicator-history` task's `decisions` for the full rationale (including why an earlier, simpler `<= bar_date` truncation attempt would have broken that "last entry matches `/analysis`" guarantee, given how the underlying weekly-resample date labeling works).

### `GET /api/portfolio`

Current positions plus account equity.

```json
{
  "equity": {
    "cash": 5000.00,
    "positions_value": 42000.00,
    "total": 47000.00
  },
  "positions": [
    {
      "id": "pos_123",
      "ticker": "AAPL",
      "quantity": 100,
      "avg_cost_basis": 195.30,
      "entry_date": "2026-05-14",
      "current_price": 228.9,
      "unrealized_pnl_pct": 17.2
    }
  ]
}
```

### `POST /api/portfolio/positions`

Add or update a position (manual entry / CSV-import row).

Request:
```json
{ "ticker": "AAPL", "quantity": 100, "avg_cost_basis": 195.30, "entry_date": "2026-05-14" }
```

Response: `201 Created`, the created/updated position object (same shape as in `GET /api/portfolio`). `current_price`/`unrealized_pnl_pct` are always `null` in this response — price enrichment happens on read, not on write.

Adding a ticker that's already held **merges** into the existing position rather than creating a duplicate row: `quantity` is summed, `avg_cost_basis` becomes the quantity-weighted average of the existing and incoming cost bases, and `entry_date` keeps the earlier of the two dates (see the `api-portfolio-add-position` task's `decisions` for the full rationale).

### `DELETE /api/portfolio/positions/{id}`

Removes a position. `204 No Content` on success.

### `GET /api/portfolio/risk`

Portfolio-level 2%/6% rule evaluation (Analyse.md §7).

```json
{
  "total_open_risk_pct": 5.4,
  "six_percent_rule_breached": false,
  "positions": [
    {
      "id": "pos_123",
      "ticker": "AAPL",
      "protective_stop": 210.15,
      "position_risk_pct": 1.8,
      "two_percent_rule_breached": false,
      "exit_flags": []
    }
  ]
}
```

`exit_flags` is a list of strings drawn from Analyse.md §7's existing-position exit conditions, e.g. `["stop_hit", "tide_flipped_bearish", "six_percent_rule_contributor"]` — empty if none apply.

A position whose risk can't be computed at all (its current price couldn't be fetched, same degrade-gracefully rule as `GET /api/portfolio`; too little daily/weekly history; a weekly-history fetch failure) is silently excluded from `positions` and from `total_open_risk_pct`, rather than appearing with partial/null fields — every field on a `positions` entry is required (see the `api-portfolio-risk` task's `decisions` for the full rationale).

### `GET /api/watchlist`

Every watched ticker, annotated with its current signal/confidence via the exact same Triple Screen signal engine `GET /api/stocks/{ticker}/analysis` uses (`app.signals.engine.analyse`, Analyse.md §5) — not a separately-implemented buy check.

```json
{
  "items": [
    {
      "ticker": "AAPL",
      "added_at": "2026-09-18T14:03:00Z",
      "signal": "BUY",
      "confidence": 72,
      "confidence_band": "High"
    },
    {
      "ticker": "ZZZZ",
      "added_at": "2026-09-10T09:15:00Z",
      "signal": null,
      "confidence": null,
      "confidence_band": null
    }
  ]
}
```

`signal`/`confidence`/`confidence_band` are `null` together on an entry whose signal couldn't be computed right now (unknown/delisted ticker, insufficient history, or the data provider being unavailable) — mirroring `PositionOut`'s `current_price`/`unrealized_pnl_pct` null-on-failure pattern rather than dropping the entry entirely (see the `api-watchlist` task's `decisions`). Ordered by `added_at` (oldest first).

### `POST /api/watchlist`

Add a ticker to the watchlist.

Request:
```json
{ "ticker": "AAPL" }
```

Response: `201 Created`, the created/existing entry (same shape as an item in `GET /api/watchlist`). `signal`/`confidence`/`confidence_band` are always `null` in this response — annotation happens on read, not on write, mirroring `POST /api/portfolio/positions`'s `current_price`/`unrealized_pnl_pct` convention.

Adding a ticker that's already watched is a **no-op**: the existing entry (original `added_at` kept) is returned unchanged, still `201`, rather than creating a duplicate row or rejecting with `409`/`422` (see the `api-watchlist` task's `decisions` for the full rationale).

### `DELETE /api/watchlist/{ticker}`

Removes a ticker from the watchlist. `204 No Content` on success, `404` if the ticker isn't on the watchlist.

## Error Cases to Cover in Tests

- Unknown ticker (`GET /api/stocks/{ticker}/...`) → `404`.
- Market data provider unavailable (both yfinance and Stooq fail) → `503` with a clear `detail`, not a raw stack trace.
- Insufficient history to compute weekly indicators (e.g. newly listed stock, <26 weeks of data) → `422` with `detail` explaining which indicator couldn't be computed, rather than silently returning partial/wrong signals. `GET /api/stocks/{ticker}/history?interval=weekly` enforces this same <26-week floor on the raw weekly series (not just on computed indicators) since it shares the same provider method as `/analysis` — a `daily`-interval request is unaffected.
- An unrecognized `range` value on `GET /api/stocks/{ticker}/history` or `GET /api/stocks/{ticker}/indicators` → `422` (FastAPI's standard per-field validation error shape, distinct from the insufficient-history `422` above).
- Duplicate position add for the same ticker → merges into the existing position (see `POST /api/portfolio/positions` above), not a `409`/`422` reject.
- Duplicate watchlist add for the same ticker → no-op, returns the existing entry unchanged (see `POST /api/watchlist` above), not a `409`/`422` reject.
- `DELETE /api/watchlist/{ticker}` for a ticker not on the watchlist → `404`.
- A watchlist ticker whose signal can't be computed → its `GET /api/watchlist` entry has `signal`/`confidence`/`confidence_band` all `null`, not a failed request (see `GET /api/watchlist` above).

## Contract Snapshot & Parallel Development

`backend/openapi.json` is a **committed snapshot** of the live schema, generated by `python scripts/export_openapi.py`. It is what makes frontend and backend work independent of each other: every route in `app/api/routers/` already has its final `response_model`, request schema, `operation_id`, and error `responses` declared (404/422/503 per endpoint, using `ErrorDetail`) even while the handler body is just a `501` stub — see the `add-api-endpoint` skill. That means the schema is contract-complete before the logic behind it exists.

Practical effect: the frontend generates its types and builds its MSW mocks straight from `backend/openapi.json` on disk. It never needs the Python backend running. Whoever is implementing a router body and whoever is building the corresponding frontend feature can work at the same time, against the same file, without blocking on each other.

**Regenerate and commit `backend/openapi.json`** any time `app/api/schemas.py` or a route's signature/response/error declarations change — before the frontend pulls the change. A stale snapshot is exactly the kind of drift this file exists to prevent.

## Frontend Type Generation

Frontend `api/types.ts` (see [Frontend.md](Frontend.md#5-api-contract-alignment)) is generated from the committed `backend/openapi.json` snapshot above, not a live server call and not hand-typed, to prevent contract drift between the two codebases.
