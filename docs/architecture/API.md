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
    "wave": { "stochastic_k": 24.3, "force_index_2ema": -18234.5, "state": "OVERSOLD_PULLBACK", "showed_pullback_in_lookback": true, "showed_rally_in_lookback": false },
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
    "bear_power": -1.4,
    "channel_upper": 236.9,
    "channel_lower": 215.9
  },
  "support_resistance_zones": [
    {
      "role": "resistance",
      "upper": 236.9,
      "lower": 233.4,
      "first_touch_date": "2026-06-02",
      "last_touch_date": "2026-08-14",
      "touch_count": 3,
      "length_days": 73,
      "length_category": "intermediate",
      "height_pct": 1.5,
      "height_category": "minor",
      "dollar_volume": 12400000000,
      "strength_score": 50,
      "broken": false,
      "break_date": null,
      "false_breakout": null
    }
  ]
}
```

`signal` ∈ `BUY | SELL | HOLD`. `confidence` is an integer 0–100. `confidence_band` ∈ `Low | Medium | High` per Analyse.md §6.

`screens.wave.state` reflects only *today's* bar. `_determine_signal` (Analyse.md §5) actually gates a fresh BUY/SELL on whether the qualifying state appeared on *any* of the last 5 trading days ("Wave shows/showed..."), not just today — `showed_pullback_in_lookback`/`showed_rally_in_lookback` expose that lookback result directly, so a client can tell "the condition was met on an earlier day within the window" apart from "it was never met at all", which `state` alone can't distinguish. Both are `null` when `screens.tide.trend` is `NEUTRAL` (Wave is never evaluated against a direction in that case); otherwise both are real booleans, including the direction that's structurally always `false` for the current tide.

`indicators.channel_upper`/`channel_lower` are the Autoenvelope/Channel band (Analyse.md §4: "EMA 13 ± avg % deviation") — `app.indicators.autoenvelope.autoenvelope`'s `mid * (1 ± avg_pct)`, where `mid` equals this same response's `ema_13`. This is the exact band `app.portfolio.exits.evaluate_exit_flags` already tests internally for the "price reaches the upper Autoenvelope band with Impulse turning Red" existing-position exit rule (Analyse.md §7), now exposed for any ticker rather than only a held portfolio position — see the `backend-channel-envelope-exposure` task's `decisions` for why this reuses the app's existing EMA(13)-backed channel rather than adding a second, slower-EMA variant. Both are `null` for the first ~100 trading days of a ticker's history, since the rolling deviation-average window (100 bars by default) isn't yet full — a much longer warm-up than any other `indicators` field, which only need up to 26 bars.

`support_resistance_zones` is a list of horizontal support/resistance zones (Analyse.md §4 row 9, Elder ch. 18) detected from swing-point clustering over the ticker's full available daily history — `app.signals.support_resistance.detect_support_resistance_zones`, computed directly in `get_analysis` (not inside `app.signals.engine.analyse()`, since it's not needed by `GET /api/stocks/{ticker}/indicators`'s per-bar `analyse_history()` loop — see the `backend-support-resistance` task's `decisions`). Up to the 15 strongest zones, ordered by `strength_score` descending. Each zone's `role` (`support`/`resistance`) is its *current* role — a broken zone keeps existing with an inverted role (old resistance becomes new support) rather than being discarded, per Elder's own rule; `broken`/`break_date` record a confirmed break, and `false_breakout` (nullable) records the most recent false-breakout episode — price closing beyond the zone, then closing back inside it within a 10-trading-day window — with `extreme_price` giving the failed move's own extreme, Elder's explicit stop-placement reference. `dollar_volume` is Elder's own `days-in-zone × average volume × average price` formula, exposed raw (not folded into `strength_score`, which is a length/height-only composite — see Analyse.md §4). This is detection + scoring + false-breakout flagging only: zones are not wired into `signal`/`confidence`/`screens` above, nor into `GET /api/portfolio/risk`'s `protective_stop` — see Analyse.md §4 and the task's `decisions` for why that's an explicit, separate follow-up.

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
      "channel_upper": 236.9,
      "channel_lower": 215.9,
      "signal": "BUY",
      "confidence": 72,
      "confidence_band": "High"
    }
  ]
}
```

`points` is oldest-first, one entry per daily bar in the requested range, produced by re-running the signal engine (`app.signals.engine.analyse`) once per bar using only that bar's own history — including Screen 1 (Tide), which is recomputed from only the weekly bars as-of that day's own calendar week (`app.signals.engine._weekly_through_bar_date`), not held fixed at today's value — so `signal`/`confidence`/Tide all genuinely vary day to day, not just the underlying daily indicators, with no look-ahead. The last entry always matches `GET /api/stocks/{ticker}/analysis` for the same ticker at the same date: for the most recent daily bar, "the weekly bars as-of that bar's calendar week" naturally reduces to the full weekly series `/analysis` itself uses — see the `api-stocks-indicator-history` task's `decisions` for the full rationale (including why an earlier, simpler `<= bar_date` truncation attempt would have broken that "last entry matches `/analysis`" guarantee, given how the underlying weekly-resample date labeling works).

`stochastic_k` and `force_index_2ema` are nullable: a bar still inside that indicator's own warm-up window (Stochastic %K(5,3,3) needs `(k_period - 1) + (smooth - 1)` prior bars — 6 with the current defaults; Force Index's raw `volume * close.diff()` input is undefined for the range's very first bar, which has no prior close) reports `null` for that field only, while every other field on the same point (including `ema_13`/`ema_26`/`macd_histogram`/`bull_power`/`bear_power`, which are EMA-seeded and never produce `NaN`) stays populated. This only affects early bars of a long-enough range (e.g. `range=max`); unlike `/analysis`, which always reports the latest bar and is therefore never still warming up.

`channel_upper`/`channel_lower` are likewise nullable, same definition/source as `/analysis`'s `indicators.channel_upper`/`channel_lower` above (per-bar, not held fixed) — but null for a much longer leading span than `stochastic_k`/`force_index_2ema`: the Autoenvelope deviation-average needs a full ~100-bar trailing window, so both bands stay null for roughly the first 100 bars of any long-enough `range` (e.g. `range=max`) before becoming real numbers for every bar after that.

Latency scales linearly with the number of daily bars in the ticker's *full* available history (not just the requested `range`), since `app.signals.engine.analyse_history` always needs the complete series for correct indicator warm-up even when `range` trims the response — see its own docstring for the precompute-and-slice design that makes this O(history_length) rather than the O(range_size × history_length) an earlier implementation had. Measured at roughly 1ms/bar (a `range=max` request against a synthetic ~11,500-bar series — about as long as AAPL's real daily history back to 1980 — completes in ~10s end to end), so a request against a ticker with decades of daily history is a multi-second, not sub-second, response; a ticker with a few years of history responds in well under a second.

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
      "unrealized_pnl_pct": 17.2,
      "signal": "BUY",
      "confidence": 72,
      "confidence_band": "High"
    }
  ]
}
```

Each position is also annotated with its current `signal`/`confidence`/`confidence_band` via the exact same Triple Screen signal engine `GET /api/stocks/{ticker}/analysis` and `GET /api/watchlist` use (`app.signals.engine.analyse`, Analyse.md §5) — not a separately-implemented buy check, reusing the same per-position market-data fetch `current_price` is derived from. `signal`/`confidence`/`confidence_band` are `null` together on a position whose signal couldn't be computed right now — either its `current_price` fetch already failed (same condition as `current_price`/`unrealized_pnl_pct` above), that fetch succeeded but the separate weekly-history fetch the signal engine additionally needs (for Screen 1/Tide) failed, or the latest daily bar has a valid close (so `current_price` is still available) but NaN open/high/low and so doesn't survive the signal engine's stricter filtering (`app.signals.engine.drop_malformed_daily_bars`) — mirroring `WatchlistItemOut`'s null-on-failure pattern rather than failing the whole request or dropping the position (see the `api-portfolio-position-signal` task's `decisions`).

### `POST /api/portfolio/positions`

Add or update a position (manual entry / CSV-import row).

Request:
```json
{ "ticker": "AAPL", "quantity": 100, "avg_cost_basis": 195.30, "entry_date": "2026-05-14" }
```

Response: `201 Created`, the created/updated position object (same shape as in `GET /api/portfolio`). `current_price`/`unrealized_pnl_pct`/`signal`/`confidence`/`confidence_band` are always `null` in this response — price/signal enrichment happens on read, not on write.

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
