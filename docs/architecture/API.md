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
    "channel_lower": 215.9,
    "rsi": 61.4,
    "season": "Summer",
    "trend_strength": { "atr": 4.2, "plus_di": 28.5, "minus_di": 15.3, "adx": 22.1 }
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
  ],
  "divergence": {
    "kind": "bullish",
    "indicator": "rsi",
    "first_extreme_date": "2026-01-16",
    "first_extreme_price": 40.0,
    "first_extreme_indicator_value": 0.0,
    "second_extreme_date": "2026-02-23",
    "second_extreme_price": 17.0,
    "second_extreme_indicator_value": 18.6,
    "bars_apart": 38,
    "centerline_crossed": null,
    "beyond_reference_line": false,
    "aborted": false
  },
  "kangaroo_tail": {
    "direction": "up",
    "tail_date": "2026-08-05",
    "confirmed_date": "2026-08-06",
    "high": 241.2,
    "low": 226.8,
    "range_multiple": 3.1,
    "suggested_stop": 234.0
  },
  "profit_target": {
    "price": 245.0,
    "source": "channel",
    "distance_to_stop": 9.3,
    "distance_to_target": 18.6,
    "reward_risk_ratio": 2.0,
    "meets_minimum_reward_risk": true
  },
  "extended_data": {
    "earnings_date": "2026-10-29",
    "earnings_within_warning_days": false,
    "ex_dividend_date": "2026-11-15",
    "shares_short": 12345678,
    "short_ratio": 2.3,
    "short_percent_of_float": 0.045,
    "float_shares": 1000000000,
    "insider_transactions": [
      {
        "insider": "Cook Timothy D",
        "position": "Chief Executive Officer",
        "transaction_text": "Sale at price 220.00 - 225.00 per share.",
        "shares": 50000.0,
        "value": 11125000.0,
        "start_date": "2026-08-15",
        "ownership": "D"
      }
    ],
    "unavailable_reason": null
  },
  "insider_clusters": [
    {
      "direction": "buy",
      "window_start_date": "2026-07-01",
      "window_end_date": "2026-07-24",
      "insiders": ["Cook Timothy D", "Kondo Christopher", "Maestri Luca"],
      "transaction_count": 3,
      "total_shares": 15000.0,
      "total_value": null
    }
  ]
}
```

`signal` ∈ `BUY | SELL | HOLD`. `confidence` is an integer 0–100. `confidence_band` ∈ `Low | Medium | High` per Analyse.md §6.

`screens.wave.state` reflects only *today's* bar. `_determine_signal` (Analyse.md §5) actually gates a fresh BUY/SELL on whether the qualifying state appeared on *any* of the last 5 trading days ("Wave shows/showed..."), not just today — `showed_pullback_in_lookback`/`showed_rally_in_lookback` expose that lookback result directly, so a client can tell "the condition was met on an earlier day within the window" apart from "it was never met at all", which `state` alone can't distinguish. Both are `null` when `screens.tide.trend` is `NEUTRAL` (Wave is never evaluated against a direction in that case); otherwise both are real booleans, including the direction that's structurally always `false` for the current tide.

`indicators.channel_upper`/`channel_lower` are the Autoenvelope/Channel band (Analyse.md §4: "EMA 13 ± avg % deviation") — `app.indicators.autoenvelope.autoenvelope`'s `mid * (1 ± avg_pct)`, where `mid` equals this same response's `ema_13`. This is the exact band `app.portfolio.exits.evaluate_exit_flags` already tests internally for the "price reaches the upper Autoenvelope band with Impulse turning Red" existing-position exit rule (Analyse.md §7), now exposed for any ticker rather than only a held portfolio position — see the `backend-channel-envelope-exposure` task's `decisions` for why this reuses the app's existing EMA(13)-backed channel rather than adding a second, slower-EMA variant. Both are `null` for the first ~100 trading days of a ticker's history, since the rolling deviation-average window (100 bars by default) isn't yet full — a much longer warm-up than any other `indicators` field, which only need up to 26 bars.

`indicators.rsi` is the Relative Strength Index (Analyse.md §4 row 10, Elder ch. 27) — `app.indicators.rsi.rsi(close)`, a 9-day, simple/arithmetic-average (not Wilder-smoothed) closing-price-only oscillator, exposed alongside `screens.wave.stochastic_k` as a second, less-noisy overbought/oversold timing tool per Elder's own comparison. Computation + exposure only — not read by `signal`/`confidence_breakdown`/`screens` above (see the `backend-indicator-rsi` task's `decisions`). `null` for the first 9 trading days of a ticker's history (needs 9 daily closing changes) — a much shorter warm-up than `channel_upper`/`channel_lower`.

`indicators.season` is the "Indicator Seasons" classification (Analyse.md §4 row 12, Elder ch. 32) — `app.signals.seasons.classify_season(macd_histogram)`, one of `Spring | Summer | Autumn | Winter` from `macd_histogram`'s bar-over-bar slope combined with its position relative to its own zero centerline (Spring: rising+below, best time to go long; Summer: rising+above, crowd-recognized uptrend, take profits on longs; Autumn: falling+above, best time to go short; Winter: falling+below, crowd-recognized downtrend, cover shorts). Purely informational — not read by `signal`/`confidence_breakdown`/`screens` above (see the `backend-indicator-seasons` task's `decisions`). `null` only when fewer than 2 daily bars are available to compute a slope from — a much shorter/rarer null condition than `channel_upper`/`channel_lower`'s ~100-bar warm-up or `rsi`'s 9-day warm-up.

`indicators.trend_strength` is the Average True Range / Directional System (Analyse.md §4 row 16, Elder ch. 24) — `app.indicators.atr.atr`/`app.indicators.directional_system.plus_minus_di`/`adx`, all built on a shared True Range (`app.indicators.atr.true_range`). `atr` is a volatility measure (the 13-day simple average of True Range); `plus_di`/`minus_di` are similarly-smoothed +DM/-DM (the portion of today's high/low extending beyond yesterday's) expressed as a percentage of smoothed True Range; `adx` is a further 13-day average of `DX = 100 * |plus_di - minus_di| / (plus_di + minus_di)` — Elder's own new-trend-detection tool (trust trend-following only while ADX rises; a 4-step rise off its own low point "rings a bell" on a new trend being born). `trend_strength` itself is always a present object, but each of its four fields is independently `null` during its own warm-up (`atr`/`plus_di`/`minus_di` need 13 bars; `adx` needs a further 13-bar window of `DX` on top of that, roughly twice as long overall). **Computation + exposure only** — not read by `signal`/`confidence_breakdown`/`screens` above (see the `backend-indicator-atr-adx` task's `decisions`).

`support_resistance_zones` is a list of horizontal support/resistance zones (Analyse.md §4 row 9, Elder ch. 18) detected from swing-point clustering over the ticker's full available daily history — `app.signals.support_resistance.detect_support_resistance_zones`, computed directly in `get_analysis` (not inside `app.signals.engine.analyse()`, since it's not needed by `GET /api/stocks/{ticker}/indicators`'s per-bar `analyse_history()` loop — see the `backend-support-resistance` task's `decisions`). Up to the 15 strongest zones, ordered by `strength_score` descending. Each zone's `role` (`support`/`resistance`) is its *current* role — a broken zone keeps existing with an inverted role (old resistance becomes new support) rather than being discarded, per Elder's own rule; `broken`/`break_date` record a confirmed break, and `false_breakout` (nullable) records the most recent false-breakout episode — price closing beyond the zone, then closing back inside it within a 10-trading-day window — with `extreme_price` giving the failed move's own extreme, Elder's explicit stop-placement reference. `dollar_volume` is Elder's own `days-in-zone × average volume × average price` formula, exposed raw (not folded into `strength_score`, which is a length/height-only composite — see Analyse.md §4). This is detection + scoring + false-breakout flagging only: zones are not wired into `signal`/`confidence`/`screens` above, nor into `GET /api/portfolio/risk`'s `protective_stop` — see Analyse.md §4 and the task's `decisions` for why that's an explicit, separate follow-up.

`divergence` (Analyse.md §4 row 11, Elder ch. 15/23/26/27) is the single most recent qualifying MACD-Histogram/Stochastic/RSI divergence — `app.signals.divergence.current_divergence`, using the same PRICE swing points (`app.signals.swing_points`) each of the three indicators' own value is read at, per-indicator, per divergence.py's own module docstring. `null` if none currently qualifies. `kind` ∈ `bullish | bearish`; `indicator` ∈ `macd_histogram | stochastic | rsi` — when more than one indicator qualifies with the same `second_extreme_date` (common, since all three are checked against the same price swing points), MACD-Histogram wins the tie-break, then Stochastic, then RSI (Elder's own preferred indicator for this signal). `bars_apart` is always 20–40 (Kerry Lovvorn's empirical spacing filter). `centerline_crossed` is non-null (always `true`) only for `indicator: "macd_histogram"` — a non-crossing pair is never reported as a divergence at all, per the book's "no crossover, no divergence" rule; `null` for stochastic/rsi, which have no such requirement. `beyond_reference_line` is the mirror: non-null only for `indicator` in `stochastic`/`rsi`, `true` when this divergence is at its textbook strongest (first extreme beyond the oscillator's own 30/70 overbought/oversold line, second back inside it) — informational only, never a requirement. `aborted` is the "Hound of the Baskervilles" state — whether price has, as of `as_of`, already ignored this divergence (continued in the "wrong" direction instead of the reversal it implied), which Elder treats as a strong continuation signal in the opposite direction rather than a failed signal to discard. **Detection + exposure only**: not wired into `signal`/`confidence_breakdown`/`screens` above — see the `backend-divergence-detection` task's `decisions`.

`kangaroo_tail` (Analyse.md §4 row 13, Elder ch. 20 "fingers") is the single most recently confirmed Kangaroo Tail reversal pattern — `app.signals.kangaroo_tail.latest_kangaroo_tail`, a pure OHLC pattern needing no other indicator series (unlike every other field on this response). `null` if none currently qualifies. `direction` ∈ `up | down` — `up` is a new high closing back down (bearish), `down` is a new low closing back up (bullish); `tail_date` is the tail bar's own date, `confirmed_date` the very next bar's date, whose own close/range is what makes this a genuinely *confirmed* pattern rather than just a matching shape (a hard gate, not an informational flag — see the `backend-kangaroo-tail-pattern` task's `decisions`). `range_multiple` is how many times the recent (10-day) average bar range this bar's own range was (always ≥ 2.5). `suggested_stop` is Elder's own explicit stop-placement rule — halfway through the tail, not at its tip (too wide) or its base (too tight) — computed as the tail bar's own range midpoint, `(high + low) / 2`. **Detection + exposure only**: not wired into `signal`/`confidence_breakdown`/`screens` above — see the `backend-kangaroo-tail-pattern` task's `decisions`.

`profit_target` (Analyse.md §7, Elder ch. 53 "How to Set Profit Targets" plus ch. 58's Tradebill formula) is a suggested profit target + reward:risk ratio — `app.portfolio.profit_target.suggest_profit_target`, computed directly in `get_analysis` (same reasoning as `support_resistance_zones` above: a single computation per request, not something `GET /api/stocks/{ticker}/indicators`'s per-bar loop needs). **Only ever non-null when `signal` is `BUY`** — this app's protective-stop formula (and its whole portfolio model) is explicitly long-only, so there's no symmetric SELL-side stop to pair a reward:risk ratio against; also `null` for a BUY when neither target technique below currently produces a candidate (e.g. a young ticker with under ~100 days of history and no yet-detected resistance zone above current price) — see the `backend-profit-target` task's `decisions`. `source` ∈ `channel | support_resistance`: `channel` is ch. 58's own Tradebill formula (current close + 30% of today's Autoenvelope/channel height, the same channel `indicators.channel_upper`/`channel_lower` expose); `support_resistance` is the nearest `support_resistance_zones` level above current close. Whichever of the two candidate prices is **tighter** (closer to current close) is used — a fixed preference order was rejected since this app has no separate "trade style" concept to pick between them by. `distance_to_stop`/`distance_to_target` are the resulting per-share risk/reward from today's close; `reward_risk_ratio` is `distance_to_target / distance_to_stop`, `null` only when `distance_to_stop <= 0` (an undefined ratio). `meets_minimum_reward_risk` is whether that ratio is `>= 2.0` — Elder's own explicit minimum ("it seldom pays to risk a dollar to make a dollar") — always a concrete `true`/`false` (never left ambiguous when the ratio itself is `null`), the explicit "flag, don't silently hide" signal this field exists for. **Detection + exposure only**: not wired into `signal`/`confidence_breakdown`/`screens` above.

`extended_data` (docs/ideas.md; Elder ch. 37/53/58) is earnings/dividend dates, short interest, and recent insider transactions -- `app.data.base.DataProvider.get_extended_data`, confirmed-live-in-yfinance fields this app didn't previously expose (see the backend-market-data-extra-fields task's `decisions` entry). `earnings_date` is the soonest upcoming earnings date (`Ticker.calendar`'s "Earnings Date" list, earliest entry -- Yahoo sometimes reports a multi-day estimate window rather than one confirmed date); `earnings_within_warning_days` is `true` when that date falls within the next 14 calendar days from today (Elder ch. 58: "a nasty earnings surprise can do serious damage to your position" -- a gap-through-the-stop risk no technical stop protects against), always `false` when `earnings_date` is null or already past. `ex_dividend_date` is `Ticker.calendar`'s "Ex-Dividend Date". `shares_short`/`short_ratio`/`short_percent_of_float`/`float_shares` are `Ticker.info`'s `sharesShort`/`shortRatio`/`shortPercentOfFloat`/`floatShares` (Elder ch. 37 pp.146-148) -- `short_ratio` ("days to cover") and `short_percent_of_float` are a rough measure of short-squeeze fuel. `insider_transactions` is `Ticker.insider_transactions` (Elder ch. 37), raw officer/director buy/sell filings in yfinance's own most-recent-first order -- `transaction_text` is yfinance's own free-text description, kept unparsed rather than classified into a structured buy/sell direction (clustering *is* computed from this same list, but as its own top-level `insider_clusters` field below, not nested here -- see that field's own paragraph). Every field above is `null`/empty either when yfinance itself simply has nothing to report for this ticker (a real "checked, nothing found" result -- yfinance's own data can be incomplete for smaller/thinly-covered tickers), or when `unavailable_reason` is set to `"fallback_provider_active"`: the fallback (Stooq) provider is currently serving market data instead of yfinance, and has no equivalent to any of this data at all, so nothing here was actually checked. `unavailable_reason` is `null` in the normal case (yfinance active), in which every null/empty field genuinely means "checked, nothing found". **Detection + exposure only**: not wired into `signal`/`confidence_breakdown`/`screens` above.

`insider_clusters` (Analyse.md's "Insider transactions" row, Elder ch. 37 p. 147) is a list of buy/sell clusters detected from `extended_data.insider_transactions` -- `app.signals.insider_clusters.detect_insider_clusters`, computed directly in `get_analysis` (same reasoning as `support_resistance_zones`/`profit_target` above). Elder's own wording is "several insiders buying (or selling) within a one-month period"; this app reads "several" as 3 and "a one-month period" as a rolling 30-calendar-day window, anchored at each cluster's own earliest qualifying transaction (not a continuously-sliding window -- see the `backend-insider-transaction-clusters` task's `decisions`). A transaction only qualifies for clustering if its own `transaction_text` classifies as an unambiguous "buy" (text starting with "purchase") or "sell" (text starting with "sale") AND it names an `insider` AND has a `start_date` -- option exercises, gifts, grants/awards, tax-withholding dispositions, and derivative-security conversions are excluded even when their text also contains "purchase"/"sale" vocabulary (e.g. "Sale+Gift..."), since they aren't genuine open-market conviction trades; a transaction missing an insider name or date can never confirm "several *distinct* insiders", so it's excluded too (still present, unaffected, in `extended_data.insider_transactions`'s raw list). `direction` ∈ `buy | sell`, detected entirely independently per direction. `insiders` is the cluster's distinct insider names (alphabetically sorted, always ≥ 3); `transaction_count` can exceed `len(insiders)` when one insider filed more than once within the window. `total_shares`/`total_value` sum whatever the window's qualifying filings reported (`null` if none of them did). Ordered most-recent-`window_end_date`-first; empty when no cluster currently qualifies. **Detection + exposure only**: not wired into `signal`/`confidence_breakdown`/`screens`/portfolio risk above -- see the task's `decisions` entry.

### `GET /api/stocks/{ticker}/indicators`

Historical indicator values and the resulting signal for each daily bar — the time-series counterpart to `/analysis`'s latest-bar-only snapshot, for charting an indicator overlay (Analyse.md §4-5).

Query params: `range` (same grammar as `/history`'s `range` — `<N>d` | `<N>w` | `<N>m` | `<N>y` | `max`, default `1y`). Daily bars only — no `interval` param, since every indicator/Screen this endpoint computes is itself daily-cadence.

```json
{
  "ticker": "AAPL",
  "points": [
    {
      "date": "2026-09-11",
      "tide": { "trend": "BULLISH", "weekly_macd_histogram_slope": "rising" },
      "ema_13": 226.4,
      "ema_26": 221.7,
      "macd_histogram": 1.82,
      "bull_power": 3.1,
      "bear_power": -1.4,
      "stochastic_k": 24.3,
      "force_index_2ema": -18234.5,
      "channel_upper": 236.9,
      "channel_lower": 215.9,
      "rsi": 61.4,
      "season": "Summer",
      "trend_strength": { "atr": 4.2, "plus_di": 28.5, "minus_di": 15.3, "adx": 22.1 },
      "signal": "BUY",
      "confidence": 72,
      "confidence_band": "High",
      "divergence": null,
      "kangaroo_tail": null,
      "obv": 1450000.0,
      "accumulation_distribution": 91500.25
    }
  ]
}
```

`points` is oldest-first, one entry per daily bar in the requested range, produced by re-running the signal engine (`app.signals.engine.analyse`) once per bar using only that bar's own history — including Screen 1 (Tide), which is recomputed from only the weekly bars as-of that day's own calendar week (`app.signals.engine._weekly_through_bar_date`), not held fixed at today's value — so `signal`/`confidence`/Tide all genuinely vary day to day, not just the underlying daily indicators, with no look-ahead. The last entry always matches `GET /api/stocks/{ticker}/analysis` for the same ticker at the same date: for the most recent daily bar, "the weekly bars as-of that bar's calendar week" naturally reduces to the full weekly series `/analysis` itself uses — see the `api-stocks-indicator-history` task's `decisions` for the full rationale (including why an earlier, simpler `<= bar_date` truncation attempt would have broken that "last entry matches `/analysis`" guarantee, given how the underlying weekly-resample date labeling works).

`tide` is the same `{ trend, weekly_macd_histogram_slope }` shape as `/analysis`'s `screens.tide` above, for this bar — never `null`: `app.signals.triple_screen.evaluate_tide` always resolves to a concrete `NEUTRAL`/`flat` result rather than an absent one even with too little weekly history to compute a slope at all, so there's no warm-up-null case here unlike `stochastic_k`/`channel_upper`/`rsi`/`season` below. Added so a client can shade a price chart's background by Screen 1 regime over time (`docs/ideas.md`'s Tide-region chart-shading idea) — see the `backend-indicator-history-tide-exposure` task's `decisions`.

`stochastic_k` and `force_index_2ema` are nullable: a bar still inside that indicator's own warm-up window (Stochastic %K(5,3,3) needs `(k_period - 1) + (smooth - 1)` prior bars — 6 with the current defaults; Force Index's raw `volume * close.diff()` input is undefined for the range's very first bar, which has no prior close) reports `null` for that field only, while every other field on the same point (including `ema_13`/`ema_26`/`macd_histogram`/`bull_power`/`bear_power`, which are EMA-seeded and never produce `NaN`) stays populated. This only affects early bars of a long-enough range (e.g. `range=max`); unlike `/analysis`, which always reports the latest bar and is therefore never still warming up.

`channel_upper`/`channel_lower` are likewise nullable, same definition/source as `/analysis`'s `indicators.channel_upper`/`channel_lower` above (per-bar, not held fixed) — but null for a much longer leading span than `stochastic_k`/`force_index_2ema`: the Autoenvelope deviation-average needs a full ~100-bar trailing window, so both bands stay null for roughly the first 100 bars of any long-enough `range` (e.g. `range=max`) before becoming real numbers for every bar after that.

`rsi` is likewise nullable, same definition/source as `/analysis`'s `indicators.rsi` above — null for the first 9 bars of any long-enough `range` (needs 9 daily closing changes), a much shorter warm-up than `stochastic_k`/`force_index_2ema`/`channel_upper`/`channel_lower`.

`season` is likewise nullable, same definition/source as `/analysis`'s `indicators.season` above (per-bar, not held fixed) — null only for the very first bar of any `range` (fewer than 2 daily bars available up to and including it), a much shorter/rarer null condition than any of `stochastic_k`/`force_index_2ema`/`channel_upper`/`channel_lower`/`rsi` above.

`trend_strength` is the same shape/definition as `/analysis`'s `indicators.trend_strength` above, for this bar (per-bar, not held fixed) — always a present object, but each of its own `atr`/`plus_di`/`minus_di`/`adx` fields is independently nullable during its own warm-up (13 bars for `atr`/`plus_di`/`minus_di`, roughly twice that for `adx`).

`divergence` is the same definition/shape as `/analysis`'s `divergence` above, restricted per-bar to only the swing points confirmable using data available through that bar (no look-ahead) — `app.signals.divergence.confirmed_divergence_as_of`, using a full-history swing-point cache (`build_divergence_swing_cache`) built once and sliced per bar rather than re-running swing-point detection on each bar's own truncated prefix (the same precompute-and-slice pattern this endpoint's other fields already use). A swing point needs the same 3-bar-each-side window `app.signals.swing_points` always requires to confirm, so a bar can lag `/analysis`'s own divergence by a few bars right after a new extreme forms — see the `backend-divergence-detection` task's `decisions` for why the swing-point detector's plateau-merging convention doesn't distort this in practice.

`kangaroo_tail` is the same definition/shape as `/analysis`'s `kangaroo_tail` above, restricted per-bar to only a tail whose own confirming bar has arrived by that bar (no look-ahead) — `app.signals.kangaroo_tail.kangaroo_tail_confirmed_as_of`, using a full-history cache (`build_kangaroo_tail_cache`) built once and filtered per bar by confirming-bar position. Unlike `divergence` above, no swing-point-style re-scan window is needed here: a candidate's qualification depends only on bars up to and including its own confirming next bar, so this stays `null` for every bar strictly between a tail's own `tail_date` and its `confirmed_date`, then reports that same tail from `confirmed_date` onward until (if ever) a later one supersedes it — see the `backend-kangaroo-tail-pattern` task's `decisions`.

`obv`/`accumulation_distribution` (Analyse.md §4 rows 14-15, Elder ch. 29) are `app.indicators.obv.obv`/`app.indicators.accumulation_distribution.accumulation_distribution` — cumulative running totals computed directly from the ticker's full `daily_ohlcv` (no Screen/gate machinery involved, unlike every other field on this response). **Never** `null`, unlike `stochastic_k`/`channel_upper`/`channel_lower`/`rsi`/`season` above: even the very first bar has a well-defined value (an undefined first-bar OBV direction, or an undefined zero-range A/D day, is mapped to a 0 contribution rather than left `NaN`, since `NaN` would otherwise poison every later cumulative total — see the `backend-indicator-obv-ad` task's `decisions`). Both are cumulative over the ticker's *entire* available history, not reset to the requested `range` window, so trimming `range` never changes an already-visible point's own `obv`/`accumulation_distribution` value — only which points are included. Not exposed on `/analysis`'s `indicators` (a single latest-bar snapshot): a cumulative series' current level in isolation is meaningless without the trailing history to compare it against. **Computation + exposure only** — not wired into `signal`/`confidence_breakdown`/`screens` above; divergence detection against either is an explicit, separate follow-up left unimplemented (depends on `app.signals.swing_points`, per the `backend-swing-point-detector` task).

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
      "confidence_band": "High",
      "entry_notes": "Breakout above resistance, strong earnings beat.",
      "strategy": "Pullback to value"
    }
  ]
}
```

Each position is also annotated with its current `signal`/`confidence`/`confidence_band` via the exact same Triple Screen signal engine `GET /api/stocks/{ticker}/analysis` and `GET /api/watchlist` use (`app.signals.engine.analyse`, Analyse.md §5) — not a separately-implemented buy check, reusing the same per-position market-data fetch `current_price` is derived from. `signal`/`confidence`/`confidence_band` are `null` together on a position whose signal couldn't be computed right now — either its `current_price` fetch already failed (same condition as `current_price`/`unrealized_pnl_pct` above), that fetch succeeded but the separate weekly-history fetch the signal engine additionally needs (for Screen 1/Tide) failed, or the latest daily bar has a valid close (so `current_price` is still available) but NaN open/high/low and so doesn't survive the signal engine's stricter filtering (`app.signals.engine.drop_malformed_daily_bars`) — mirroring `WatchlistItemOut`'s null-on-failure pattern rather than failing the whole request or dropping the position (see the `api-portfolio-position-signal` task's `decisions`).

`entry_notes` is the free-text "why did I take this trade" note from Elder ch. 59's Trade Journal Section A (`docs/ideas.md`'s ch. 59 entry) — optional, `null` if none was ever recorded (see `POST /api/portfolio/positions` below).

`strategy` is the trader's own personal, named strategy/setup tag (Elder ch. 55/56/58/59, `docs/ideas.md`'s ch. 55/56 entry — his own examples: "false breakout with a divergence," "pullback to value") — optional free-text, `null` if none was ever given. Free-text rather than a fixed, predefined list, since Elder is explicit that a trader's strategies are personal and evolve over time ("you may develop new strategies and drop others") — see the `backend-trade-strategy-tagging` task's `decisions`.

### `POST /api/portfolio/positions`

Add or update a position (manual entry / CSV-import row).

Request:
```json
{ "ticker": "AAPL", "quantity": 100, "avg_cost_basis": 195.30, "entry_date": "2026-05-14", "entry_notes": "Breakout above resistance, strong earnings beat.", "strategy": "Pullback to value" }
```

`entry_notes`/`strategy` are both optional and free-text. Response: `201 Created`, the created/updated position object (same shape as in `GET /api/portfolio`). `current_price`/`unrealized_pnl_pct`/`signal`/`confidence`/`confidence_band` are always `null` in this response — price/signal enrichment happens on read, not on write.

Adding a ticker that's already held **merges** into the existing position rather than creating a duplicate row: `quantity` is summed, `avg_cost_basis` becomes the quantity-weighted average of the existing and incoming cost bases, and `entry_date` keeps the earlier of the two dates (see the `api-portfolio-add-position` task's `decisions` for the full rationale). `entry_notes` merges by **appending**: an incoming note is added to the existing one separated by a blank line rather than overwriting it (so notes from multiple buys into the same position are all preserved); a merge with no incoming note leaves the existing note untouched — see the `backend-trade-journal-entry-notes` task's `decisions`. `strategy` merges differently, by **overwriting**: an incoming `strategy` replaces the existing tag outright rather than being concatenated onto it, so this field stays a single clean value for future strategy-segmented grouping/equity-curve use (`docs/ideas.md`'s ch. 59 "equity curves segmented by strategy" idea); a merge with no incoming `strategy` leaves the existing one untouched — see the `backend-trade-strategy-tagging` task's `decisions`.

### `DELETE /api/portfolio/positions/{id}`

Removes a position. `204 No Content` on success.

Query params: `exit_reason` (optional, one of `target_hit` | `stop_hit` | `reached_value_zone` | `going_nowhere` | `starting_to_turn` | `couldnt_stand_the_pain` | `recognized_junk_trade_after_entry` | `unspecified` — Elder's own exit-reason taxonomy per Analyse.md §7/ideas.md's ch. 51 note, plus `unspecified` as this app's own default); `exit_price`/`exit_date` (optional, must be supplied together or not at all — see below). Also records a `closed_trades` row (ticker, quantity, entry price/date, exit price/date, realized P&L, exit_reason, entry_notes, strategy) for the trade-history/ledger this app previously had no model for at all. `entry_notes`/`strategy` are both carried over verbatim from the position's own values.

By default (`exit_price`/`exit_date` omitted), the closed trade is priced at today's latest close for this ticker (the same market-data lookup `current_price` uses elsewhere, not a caller-supplied price) — see the `backend-trade-history-table` task's `decisions`. If that price fetch fails, the position is still deleted but no `closed_trades` row is recorded (there's no exit price to compute a realized P&L from). Callers may instead supply `exit_price` (positive, finite) and `exit_date` (not before the position's `entry_date`) together to backfill a trade that already happened in the past — e.g. importing real trading history, or logging a sale a few days late with its actual fill price — bypassing the live-price lookup entirely for that request. `422` if only one of the pair is given, or if `exit_date` predates `entry_date`. See the `backend-close-position-manual-exit` task's `decisions` for why this is a deliberate, narrow exception to `backend-trade-history-table`'s original "always price from live market data" rule rather than a silent override of it.

### `GET /api/portfolio/risk`

Portfolio-level 2%/6% rule evaluation (Analyse.md §7).

```json
{
  "total_open_risk_pct": 5.4,
  "realized_losses_this_month_pct": 0.0,
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

`total_open_risk_pct` is the book's actual *two-part* 6% Rule total (Analyse.md §7, per `docs/ideas.md`'s ch. 51 cross-check — the book's own worked example sums "the sum of your losses for the current month" AND "the risks in open trades"): `realized_losses_this_month_pct` (this calendar month's realized losses from `closed_trades`, populated by `DELETE /api/portfolio/positions/{id}` — only losing trades count, a profitable month contributes 0) plus the sum of `position_risk_pct` across every open position with a known stop. The field keeps its original name despite now covering both halves (see the `backend-trade-history-table` task's `decisions`).

A position whose risk can't be computed at all (its current price couldn't be fetched, same degrade-gracefully rule as `GET /api/portfolio`; too little daily/weekly history; a weekly-history fetch failure) is silently excluded from `positions` and from the open-risk half of `total_open_risk_pct`, rather than appearing with partial/null fields — every field on a `positions` entry is required (see the `api-portfolio-risk` task's `decisions` for the full rationale).

### `GET /api/portfolio/closed-trades`

Trade history (the `closed_trades` table `DELETE /api/portfolio/positions/{id}` populates), most recently exited first, each row annotated with its buy/sell/trade "A-trade" grades (Elder ch. 55 "Is This an A-Trade?", Analyse.md §7 — see the `backend-trade-grading` task).

```json
{
  "items": [
    {
      "id": "trade_abc123",
      "ticker": "ADSK",
      "quantity": 100,
      "entry_price": 51.77,
      "entry_date": "2026-03-02",
      "exit_price": 53.78,
      "exit_date": "2026-03-09",
      "realized_pnl": 201.0,
      "exit_reason": "target_hit",
      "buy_grade_pct": 97.3,
      "sell_grade_pct": 35.5,
      "trade_grade_pct": 32.1,
      "trade_letter_grade": "A",
      "entry_notes": "Breakout above resistance, strong earnings beat.",
      "strategy": "Pullback to value",
      "follow_up_notes": null,
      "follow_up_reviewed_at": null
    }
  ]
}
```

The three grade fields are `null` whenever they can't currently be computed — the ticker's daily-history fetch failed, `entry_date`/`exit_date` isn't an exact trading-day row in that history (e.g. it predates the fetched history), or (`trade_grade_pct` only) `entry_date` falls inside the Autoenvelope/channel's own ~100-bar warm-up window (same warm-up `GET /api/stocks/{ticker}/analysis`'s `indicators.channel_upper`/`channel_lower` document) — never a request-level error; the row itself is always present with its recorded price/date/P&L fields intact. See `app.portfolio.grading` for the formulas themselves.

`trade_letter_grade` is Elder's own A/B/C/D letter grade (ch. 55 "Is This an A-Trade?" footnote: "A is excellent, B good, C mediocre, and D poor"), derived from `trade_grade_pct`: `A` >= 30%, `B` in [20%, 30%), `C` in [10%, 20%), `D` < 10% (no floor — a losing trade is still "poor"). The book only gives two numeric anchors (>=30% "A", ~10% "C"); the B/D thresholds fill that gap by even 10-point-per-letter spacing implied by those two anchors — see the `backend-trade-grade-letter` task's `decisions` for the full rationale and alternatives considered. `null` exactly when `trade_grade_pct` is `null`. `buy_grade_pct`/`sell_grade_pct` deliberately stay percentage-only — the book gives them no letter-grade scale at all, only a single ">50% = very good" anchor each.

`entry_notes` is carried over verbatim from the position's own `entry_notes` (Elder ch. 59 Trade Journal Section A) at the moment it was closed — `null` if the position never had a note recorded. `strategy` is carried over the same way (Elder ch. 55/56/58/59's personal named strategy tag) — `null` if the position never had a strategy tag recorded.

`follow_up_notes`/`follow_up_reviewed_at` record Elder's mandatory two-months-later follow-up review (ch. 59 Trade Journal Section E, docs/ideas.md's ch. 59 entry) — both `null` until `POST /api/portfolio/closed-trades/{trade_id}/follow-up-review` (below) has been called for this trade.

An optional `?due_for_follow_up=true` query parameter narrows the response to trades due for that review right now: `follow_up_reviewed_at` still `null` and `exit_date` between 8 and 10 weeks ago inclusive — see the `backend-trade-journal-followup-review` task's `decisions` entry for why an 8-10-week band (not a single exact "exactly 2 months" date) was chosen. Defaults to `false` (every closed trade, unfiltered).

### `POST /api/portfolio/closed-trades/{trade_id}/follow-up-review`

Records Elder's mandatory two-months-later follow-up review (ch. 59 Trade Journal Section E) for one closed trade: reopening it with the benefit of hindsight and writing what it teaches.

Request:

```json
{ "follow_up_notes": "Sold too early -- the tide was still bullish two months later." }
```

`follow_up_notes` is required and must not be blank/whitespace-only (leading/trailing whitespace is stripped) — unlike `entry_notes` above, this endpoint's entire purpose is recording that note.

Response: the full updated `ClosedTradeOut` (same shape as a `GET /api/portfolio/closed-trades` item, including a freshly recomputed grade), with `follow_up_notes` set and `follow_up_reviewed_at` set to now (naive UTC).

Calling this again for the same `trade_id` overwrites both fields with the new call's values (not append, not reject) — see this task's `decisions` entry. Not restricted to trades the due-for-follow-up filter above would currently surface; a trade can be reviewed early, late, or reviewed more than once. 404s if `trade_id` doesn't exist.

### `POST /api/portfolio/trade-apgar`

Elder ch. 58's "Trade Apgar" (Analyse.md §7 / docs/ideas.md ch. 58) — a fixed 5-question, 0/1/2-each pre-trade go/no-go score matching Elder's own example strategy, the pre-trade counterpart to `GET /api/portfolio/closed-trades`'s after-the-fact grading. Stateless — nothing is persisted, this just scores whatever `ticker`/manual answers the request supplies at the time of the call.

Request:

```json
{
  "ticker": "AAPL",
  "false_breakout_status": "on_the_verge",
  "perfection": "one"
}
```

Response:

```json
{
  "ticker": "AAPL",
  "questions": [
    { "key": "weekly_impulse", "label": "Weekly Impulse", "value": "GREEN", "score": 1, "source": "auto" },
    { "key": "daily_impulse", "label": "Daily Impulse", "value": "BLUE", "score": 2, "source": "auto" },
    { "key": "price_vs_value", "label": "Daily price vs. value", "value": "below_value", "score": 2, "source": "auto" },
    { "key": "false_breakout", "label": "False breakout status", "value": "on_the_verge", "score": 2, "source": "manual" },
    { "key": "perfection", "label": "\"Perfection\" (both timeframes look ideal)", "value": "one", "score": 1, "source": "manual" }
  ],
  "total_score": 8,
  "go": true
}
```

Three of the five questions are auto-populated (`source: "auto"`) from the same `app.signals.engine.analyse()` pipeline every other signal-facing endpoint uses for `ticker`: `weekly_impulse`/`daily_impulse` are the weekly/daily Impulse System colors (Analyse.md §3, `weekly_impulse` via `app.signals.impulse.evaluate_impulse` run directly on the fetched weekly OHLCV — the same computation Screen 1/Tide uses internally, since `analyse()` itself only exposes that color already mapped onto BULLISH/BEARISH/NEUTRAL), and `price_vs_value` classifies today's close against ch. 41's EMA(13)/EMA(26) "value zone" — **not** the Autoenvelope/channel band `channel_upper`/`channel_lower` (a distinct indicator drawn on the same chart) — into `above_value` (0)/`in_value_zone` (1)/`below_value` (2). `false_breakout_status`/`perfection` are always the caller's own manual inputs (`none`/`already_happened`/`on_the_verge` and `neither`/`one`/`both` respectively), echoed back verbatim as `value` — this first version derives no suggested starting value for either from `app.signals.kangaroo_tail`/`app.signals.support_resistance`, even though both detect closely related patterns (see the `backend-trade-apgar` task's `decisions`).

`go` is Elder's own explicit rule: `total_score >= 7` **and** no single question scored 0 — both conditions required together. A trade scoring 8 total with one question at 0 still gets `go: false`.

Errors: unknown ticker → `404`; `ticker`'s fetched weekly history has fewer than 26 weeks (same minimum `GET /api/stocks/{ticker}/analysis`'s weekly fetch enforces), or its fetched daily history is empty once any malformed bar is dropped → `422`; market data provider unavailable → `503`.

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

### `GET /api/watchlist/breadth`

"Personal breadth" — a cheap, no-new-data-source proxy for true market breadth (Analyse.md's Personal breadth proxy section, per `docs/ideas.md`'s ch. 34-36 entry). Counts/percentages of BULLISH/BEARISH/NEUTRAL Screen 1 (Tide) trend across every distinct ticker the user is tracking (the union of the watchlist and portfolio, deduplicated).

```json
{
  "tracked_ticker_count": 4,
  "bullish_count": 2,
  "bearish_count": 1,
  "neutral_count": 1,
  "unavailable_count": 0,
  "bullish_pct": 50.0,
  "bearish_pct": 25.0,
  "neutral_pct": 25.0
}
```

A tracked ticker whose Tide can't be computed right now (unknown/delisted ticker, insufficient history, or the data provider being unavailable) is counted in `unavailable_count` and excluded from the BULLISH/BEARISH/NEUTRAL counts and the percentages — mirroring `GET /api/watchlist`'s own null-signal-on-failure convention rather than guessing. An empty watchlist+portfolio (or one where every tracked ticker is currently unavailable) returns all-zero counts and `0.0` percentages, not an error. Computed fresh on every request, not cached at this aggregation layer — see the `backend-watchlist-breadth-proxy` task's `decisions`.

`bullish_pct`/`bearish_pct`/`neutral_pct` are each rounded independently to 1 decimal place, so they don't always sum to exactly 100.0 (an even 3-way split rounds to 33.3 + 33.3 + 33.3 = 99.9) — a client rendering all three should not assume they total 100, and shouldn't "fix" the display by silently adjusting one bucket. See `docs/Analyse.md`'s Personal breadth proxy section.

### `POST /api/daily-homework`

Records Elder ch. 57's "Am I ready to trade?" 5-question daily psychological readiness self-test (`docs/ideas.md`'s ch. 57 entry) — purely subjective, no market data or data-provider dependency at all. Scoped to just this 5-question self-test, not ch. 57's broader 17-line market-context homework spreadsheet.

Request:

```json
{
  "date": "2026-09-21",
  "physical_state_score": 2,
  "yesterday_trading_score": 1,
  "trade_planning_score": 2,
  "mood_score": 2,
  "schedule_score": 1
}
```

`date` is optional, defaulting to today (server UTC date) — a caller may also backfill/correct a past day. Each of the five scores is an integer `0`/`1`/`2` per the book's own scale; any other value is `422`. Submitting a `date` that already has a recorded entry **overwrites** that day's scores rather than rejecting the request or creating a second row for the same day — always `201` either way (mirrors `POST /api/portfolio/positions`/`POST /api/watchlist`'s identical "same status code whether created or updated/merged" convention).

Response, `201 Created`:

```json
{
  "date": "2026-09-21",
  "physical_state_score": 2,
  "yesterday_trading_score": 1,
  "trade_planning_score": 2,
  "mood_score": 2,
  "schedule_score": 1,
  "total_score": 8,
  "band": "green",
  "recorded_at": "2026-09-21T13:05:00Z"
}
```

`total_score` (0-10) and `band` are pure computations over the five scores (`app.portfolio.homework.band_for_total_score`), never stored themselves. `band` follows the book's own color thresholds: `<=4` → `red` ("don't trade"), `5`-`6` → `yellow` ("trade cautiously"), `7`-`8` → `green`, `9`-`10` → `yellow` again (Elder's own note: "with everything so perfect, any change is bound to be for the worse").

### `GET /api/daily-homework/today`

Today's (server UTC date) recorded entry, or a null `entry` if today's self-test hasn't been recorded yet — never a `404`, since "not done yet today" is the normal, expected state at the start of every day, not an error.

```json
{ "entry": null }
```

### `GET /api/daily-homework`

Every recorded self-test entry (same shape as `POST /api/daily-homework`'s response), most recent `date` first.

```json
{ "items": [ { "date": "2026-09-21", "physical_state_score": 2, "yesterday_trading_score": 1, "trade_planning_score": 2, "mood_score": 2, "schedule_score": 1, "total_score": 8, "band": "green", "recorded_at": "2026-09-21T13:05:00Z" } ] }
```

### `GET /api/daily-homework/yesterday-trading-suggestion`

A suggested (never auto-applied) value for the "how did I trade yesterday?" question, derived from the net `realized_pnl` of every `closed_trades` row exited yesterday (server UTC "today" minus one day) — a cheap, optional enhancement over Elder's own fully-manual-recall version of this question (see the `backend-daily-homework-self-test` task's `decisions` entry for why this stays a suggestion, never a value this app writes on the user's behalf).

```json
{ "as_of_date": "2026-09-20", "net_realized_pnl": 150.0, "suggested_score": 2 }
```

`net_realized_pnl` and `suggested_score` are both `null` when no position was closed yesterday — there's nothing to base a suggestion on, so the question stays fully manual for that day. Otherwise a net gain suggests `2`, exactly breakeven suggests `1`, and a net loss suggests `0` — the same 0/1/2 scale as every other question. A caller (e.g. the daily homework form) may use `suggested_score` to pre-fill `POST /api/daily-homework`'s `yesterday_trading_score`, but that field is always the user's own explicit answer, never overwritten automatically.

### `GET /api/ibkr/status`

Whether the optional IBKR Client Portal Gateway integration (`app.data.ibkr_provider.IBKRProvider`, gated behind `Settings.ibkr_enabled` — `false` by default, since no environment other than a real user's own machine has a locally-running, authenticated IB Gateway) is usable right now. Read-only — never triggers a login attempt or any data fetch itself, and never fails: every state below is returned as a normal `200`.

```json
{ "state": "available", "detail": null }
```

`state` ∈ `disabled | available | gateway_unreachable | not_authenticated`. `disabled` is this endpoint's own addition on top of `app.data.ibkr_provider.GatewayState`'s three values — set whenever `Settings.ibkr_enabled` is `False`, without ever attempting to reach a gateway at all. Otherwise `state` is exactly what `IBKRProvider.get_gateway_status()` reports: `available` (gateway running, session authenticated — IBKR-backed features can be used), `gateway_unreachable` (no gateway process answered at the configured base URL — most likely it isn't running), or `not_authenticated` (the gateway is up but its interactive browser login step hasn't been completed, or the session has since expired). `detail` is optional human-readable context (the underlying transport error, or the gateway's own message) — never required for a caller to branch on; always `null` for `disabled` and usually `null` for `available`. See the `backend-ibkr-status-endpoint` task's `decisions` entry.

### `GET /api/ibkr/scanner/params`

Lists IBKR's own predefined market-scanner categories (`IBKRProvider.get_scanner_params`'s `scan_type_list` — 52-week-high/low, hot-by-volume, top % gainers/losers, etc.) so a caller can build a `POST /api/ibkr/scanner/run` request. This is the "scan a large universe you don't already track" feature docs/ideas.md's ch. 56 entry describes — distinct from the watchlist (a curated list of already-tracked tickers) and the ticker detail view (analyzes one already-chosen ticker). Elder's own bespoke MACD-divergence-precursor scanner is explicitly out of scope; this only exposes IBKR's own existing scan categories.

Reuses `GET /api/ibkr/status`'s exact availability pattern for a genuinely-unavailable gateway/session: a normal `200` with a `state` value, never a failed request.

```json
{ "state": "available", "detail": null, "categories": [{ "code": "TOP_PERC_GAIN", "display_name": "Top % Gainers" }] }
```

`state` ∈ `disabled | available | gateway_unreachable | not_authenticated`, same meaning as `GET /api/ibkr/status`'s `state`. `categories` is IBKR's own `scan_type_list` passed through as-is (field shape is entirely gateway-defined and not modeled by this app) — non-null if and only if `state` is `available`; an empty list is a valid response if the gateway's own params payload has no `scan_type_list`. See the `backend-market-scanner` task's `decisions` entry for why this is a pass-through rather than a hand-curated subset.

A transient failure of this specific call (a non-200 response, transport error, or unparseable body from `/iserver/scanner/params`) is a genuinely different situation from the gateway/session being unavailable, even though `IBKRProvider` raises the same `IBKRUnavailableError` for both: a fresh `get_gateway_status()` check (a different endpoint, `/iserver/auth/status`) can still report `available` in this case. Reporting `state: "available"` with `categories: null` here would violate the non-null-iff-`available` invariant above, so this case is instead surfaced as `503` with a plain-text `detail` — see the `backend-market-scanner` task's `review` finding and its fix.

### `POST /api/ibkr/scanner/run`

Runs a market scan via `IBKRProvider.run_scanner`, using a `scan_config` built from `GET /api/ibkr/scanner/params`'s option lists.

Request:

```json
{ "scan_config": { "instrument": "STK", "type": "TOP_PERC_GAIN", "location": "STK.US.MAJOR" } }
```

`scan_config` is passed to the gateway as-is — this app doesn't validate or transform it, matching `IBKRProvider.run_scanner`'s own contract. Ch. 56's liquidity-filter advice (exclude illiquid names, roughly <500k–1M average daily volume) is applied by including IBKR's own volume-floor filter code from `get_scanner_params`'s filter option list in `scan_config.filter` — this endpoint doesn't inject a default filter automatically (see the `backend-market-scanner` task's `decisions` entry for why).

Response, same `state`/`detail` convention as `GET /api/ibkr/scanner/params`, plus `results`:

```json
{
  "state": "available",
  "detail": null,
  "results": [{ "conid": 265598, "symbol": "AAPL", "company_name": "Apple Inc", "rank": 1 }]
}
```

`results` is non-null if and only if `state` is `available`; an empty list is a valid, successful zero-match scan. Being rate-limited (`IBKRProvider.run_scanner`'s own client-side 1-request/second throttle) is a distinct, genuine, transient error for an otherwise-available scanner — surfaced as `429`, not folded into `state` — since it's actionable (retry shortly) in a way "IBKR isn't connected" isn't. This endpoint doesn't add a second, competing throttle of its own; it relies entirely on `IBKRProvider`'s existing rate limits (1 req/sec for `run_scanner`, a 15-minute cache for `get_scanner_params`). Same `503` treatment as `GET /api/ibkr/scanner/params` for a transient failure of the scan call itself against an otherwise-`available` gateway.

### `POST /api/ibkr/breadth/snapshot`

Elder ch. 34-36's real, broad-market breadth indicators (New High-New Low, Advance/Decline) — distinct from `GET /api/watchlist/breadth`'s personal-watchlist-only Tide aggregate. Records (at most once per calendar day) `len(IBKRProvider.run_scanner(scan_config))` for one caller-labeled `series_key`, and returns 5-day/20-day rolling sums over that series' own accumulated daily history. See the `backend-market-breadth-indicators` task's `decisions` entry for the research finding that shaped this scope — IBKR's scanner returns a ranked, capped shortlist of matching contracts, never a genuine full-market count or percentage, so this is an explicitly bounded approximation, and "Stocks above 50-Day MA" (ch. 35) isn't implemented at all (no IBKR scan category maps to a moving-average comparison, unlike NH-NL/Advance-Decline's plausible new-high/new-low- and gainer/loser-style categories) — and docs/Analyse.md's "IBKR-scanner breadth approximation" section for the full caveat.

Request:

```json
{ "series_key": "nh", "scan_config": { "instrument": "STK", "type": "TOP_PERC_GAIN", "location": "STK.US.MAJOR" } }
```

`series_key` is an opaque, caller-chosen label (lowercase letters/digits/underscore/hyphen, 1-40 chars) for one side of a breadth reading (e.g. `"nh"`/`"nl"` for New High-New Low, `"adv"`/`"dec"` for Advance/Decline) — this app doesn't hardcode which IBKR scan-type code corresponds to which side (unconfirmed against a live gateway, same reasoning as `POST /api/ibkr/scanner/run`'s own `scan_config`); the caller supplies both the label and the `scan_config` that produces it, and combines two labeled readings into a spread itself (e.g. `nh.rolling_5d - nl.rolling_5d`).

Response:

```json
{
  "state": "available",
  "detail": null,
  "series_key": "nh",
  "snapshot_date": "2026-09-21",
  "count": 7,
  "days_recorded": 23,
  "rolling_5d": 31,
  "rolling_20d": 118
}
```

`count` is non-null if and only if `state` is `available`. At most one scan is run per `series_key` per calendar day: if today's row (`app.db.models.IBKRBreadthSnapshotORM`) already exists, it's served directly and the request's `scan_config` is ignored — not a stateless per-request computation, since the rolling windows below need an accumulated daily history, and re-scanning on every request would also needlessly spend `IBKRProvider.run_scanner`'s rate-limited calls. `rolling_5d` (ch. 34's "weekly NH-NL", a 5-trading-day moving total) and `rolling_20d` (ch. 34's "20-day NH-NL", a rolling monthly look-back) sum `count` over this series' most recent recorded days (ending today); each is `null` until enough days exist (`days_recorded >= 5`/`20` respectively) rather than a misleadingly partial sum. `days_recorded` is the total number of calendar days (including today) recorded for this `series_key` so far, uncapped by either rolling window.

None of ch. 34-36's own numeric thresholds (weekly NH-NL −4,000/+2,500, 20-day NH-NL −500, 50-day-MA 75%/25%) are surfaced anywhere in this response — see docs/Analyse.md for why they don't apply to this bounded approximation.

'disabled'/`gateway_unreachable`/`not_authenticated` states behave exactly like `POST /api/ibkr/scanner/run` — a normal `200` response, never an HTTP error, with every other field `null`. Being rate-limited or a transient scanner-call failure against an otherwise-`available` gateway are surfaced as `429`/`503` respectively, exactly like `POST /api/ibkr/scanner/run` — both only reachable on a cache miss (today's first request for this `series_key`).

## Error Cases to Cover in Tests

- Unknown ticker (`GET /api/stocks/{ticker}/...`) → `404`.
- Market data provider unavailable (both yfinance and Stooq fail) → `503` with a clear `detail`, not a raw stack trace.
- Insufficient history to compute weekly indicators (e.g. newly listed stock, <26 weeks of data) → `422` with `detail` explaining which indicator couldn't be computed, rather than silently returning partial/wrong signals. `GET /api/stocks/{ticker}/history?interval=weekly` enforces this same <26-week floor on the raw weekly series (not just on computed indicators) since it shares the same provider method as `/analysis` — a `daily`-interval request is unaffected.
- An unrecognized `range` value on `GET /api/stocks/{ticker}/history` or `GET /api/stocks/{ticker}/indicators` → `422` (FastAPI's standard per-field validation error shape, distinct from the insufficient-history `422` above).
- Duplicate position add for the same ticker → merges into the existing position (see `POST /api/portfolio/positions` above), not a `409`/`422` reject.
- Duplicate watchlist add for the same ticker → no-op, returns the existing entry unchanged (see `POST /api/watchlist` above), not a `409`/`422` reject.
- `DELETE /api/watchlist/{ticker}` for a ticker not on the watchlist → `404`.
- A tracked ticker (watchlist or portfolio) whose Tide can't be computed → counted in `GET /api/watchlist/breadth`'s `unavailable_count`, not a failed request (see `GET /api/watchlist/breadth` above).
- A watchlist ticker whose signal can't be computed → its `GET /api/watchlist` entry has `signal`/`confidence`/`confidence_band` all `null`, not a failed request (see `GET /api/watchlist` above).
- A `POST /api/daily-homework` score outside `0`-`2` → `422` (standard per-field validation error shape).
- `GET /api/daily-homework/today` before today's entry has been recorded, or `GET /api/daily-homework/yesterday-trading-suggestion` with no `closed_trades` row exited yesterday → a normal `200` with a null `entry`/`net_realized_pnl`+`suggested_score`, never a failed request (see both endpoints above).
- IBKR disabled/gateway unreachable/not authenticated on `GET /api/ibkr/scanner/params` or `POST /api/ibkr/scanner/run` → a normal `200` with the corresponding `state`, `categories`/`results` both `null`, never a failed request (see both endpoints above).
- `POST /api/ibkr/scanner/run` called again sooner than `IBKRProvider`'s own 1-request/second `run_scanner` throttle allows → `429` (see `POST /api/ibkr/scanner/run` above).
- The scanner-params/scanner-run call itself fails transiently against a gateway a fresh check still reports `available` (distinct from the gateway/session genuinely being unavailable) → `503` on `GET /api/ibkr/scanner/params` or `POST /api/ibkr/scanner/run`, never `state: "available"` with `categories`/`results` left `null` (see both endpoints above).
- IBKR disabled/gateway unreachable/not authenticated on `POST /api/ibkr/breadth/snapshot` → a normal `200` with the corresponding `state`, every other field `null`, never a failed request; same `429`/`503` treatment as `POST /api/ibkr/scanner/run` for rate-limiting/a transient scan-call failure, both only reachable on a cache miss (see `POST /api/ibkr/breadth/snapshot` above).
- An invalid `series_key` (not `^[a-z0-9_-]{1,40}$`) on `POST /api/ibkr/breadth/snapshot` → `422` (standard per-field validation error shape).

## Contract Snapshot & Parallel Development

`backend/openapi.json` is a **committed snapshot** of the live schema, generated by `python scripts/export_openapi.py`. It is what makes frontend and backend work independent of each other: every route in `app/api/routers/` already has its final `response_model`, request schema, `operation_id`, and error `responses` declared (404/422/503 per endpoint, using `ErrorDetail`) even while the handler body is just a `501` stub — see the `add-api-endpoint` skill. That means the schema is contract-complete before the logic behind it exists.

Practical effect: the frontend generates its types and builds its MSW mocks straight from `backend/openapi.json` on disk. It never needs the Python backend running. Whoever is implementing a router body and whoever is building the corresponding frontend feature can work at the same time, against the same file, without blocking on each other.

**Regenerate and commit `backend/openapi.json`** any time `app/api/schemas.py` or a route's signature/response/error declarations change — before the frontend pulls the change. A stale snapshot is exactly the kind of drift this file exists to prevent.

## Frontend Type Generation

Frontend `api/types.ts` (see [Frontend.md](Frontend.md#5-api-contract-alignment)) is generated from the committed `backend/openapi.json` snapshot above, not a live server call and not hand-typed, to prevent contract drift between the two codebases.
