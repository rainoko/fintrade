# Backend Architecture

Python 3.12+, FastAPI. See [Architecture.md](../Architecture.md) for how this fits the overall system, and [Analyse.md](../Analyse.md) for the methodology this implements.

## 1. Why Python (not Go)

The core value of this app is computing Elder's specific indicator set (EMA, MACD-Histogram, Force Index, Stochastic, Elder-Ray, Autoenvelope) correctly and combining them into a signal + confidence score. `pandas` makes this tractable and `yfinance` is Python-native. Go has no equivalent ecosystem here — building this in Go means hand-rolling every indicator and reimplementing (or shelling out for) Yahoo/Stooq access, for no benefit this project needs (no high-throughput/low-latency requirement).

Indicators are implemented directly on top of `pandas` (`ewm`/`rolling`), not `pandas-ta`: as of this writing `pandas-ta`'s only installable release requires Python 3.12+ (older releases were pulled from PyPI), which would have forced a language-version bump onto the whole project for a dependency whose formulas don't always match Elder's book definitions anyway. Hand-writing the handful of indicators this project needs, directly against their Analyse.md §4 definitions, avoids both problems.

## 2. Module Layout

```
backend/
  app/
    data/          # market data adapters
      base.py          # DataProvider protocol (interface)
      yfinance_provider.py
      stooq_provider.py
      cache.py         # SQLite-backed OHLCV + extended-data cache
      exceptions.py    # shared DataProviderError hierarchy (TickerNotFoundError, InsufficientHistoryError, DataProviderUnavailableError)
      ibkr_provider.py # optional IBKR Client Portal Web API provider (hourly bars + scanner) -- not a DataProvider, see §8
      cftc_cot_provider.py # CFTC Commitments of Traders (futures positioning) -- not a DataProvider, see §9
      day_trader_intraday.py # IBKR intraday bars for the active day-trader TimeframeTriple's MINUTE-unit leg(s) -- see §10
    indicators/    # pure functions, one indicator per module
      ema.py
      macd.py
      force_index.py
      stochastic.py
      elder_ray.py
      autoenvelope.py
      rsi.py
      _validation.py   # shared package-internal helpers (e.g. validate_period), no I/O
    signals/
      triple_screen.py   # Screen 1/2/3 evaluation
      impulse.py          # Impulse System gate
      confidence.py        # weighted scoring (Analyse.md §6)
      engine.py             # orchestrates the above into BUY/SELL/HOLD + %
      _swing_extremes.py      # package-internal: vectorized centered-rolling max/min primitive shared by swing_points.py and support_resistance.py
      swing_points.py        # shared fractal swing-high/swing-low detector (single series)
      support_resistance.py  # horizontal S/R zone detection + false-breakout flagging
      divergence.py           # MACD-H/Stochastic/RSI divergence detection (Analyse.md §4 row 11)
      kangaroo_tail.py         # Kangaroo Tail ("fingers") reversal-pattern detection (Analyse.md §4 row 13)
      timeframe.py             # generic long-term/intermediate/short-term TimeframeTriple model (ch. 39, docs/tasks/backend-day-trader-timeframe-mode.json) -- foundational domain model only, not yet read by triple_screen.py/engine.py (see §10)
      insider_clusters.py      # insider-transaction buy/sell classification + cluster detection (Elder ch. 37 p. 147)
    portfolio/
      models.py        # Position, Account (Pydantic/SQLAlchemy)
      pricing.py         # shared mark-to-market price enrichment (EnrichedPosition)
      risk.py           # 2% rule, 6% rule, protective stop calc
      exits.py           # existing-position exit rules (Analyse.md §7)
      profit_target.py    # suggested profit target + reward:risk ratio; signal-agnostic itself, gated BUY-only by one caller (fresh-signal analysis) but computed unconditionally by the other (an already-open position) (Analyse.md §7)
    trading_mode.py    # global trading-mode settings persistence (docs/tasks/backend-day-trader-timeframe-mode.json §10) -- top-level, parallel to config.py, not nested under portfolio/ or signals/
    db/
      models.py         # SQLAlchemy ORM models
      session.py
      migrations/        # Alembic
    api/
      routers/
        stocks.py
        portfolio.py
      schemas.py        # Pydantic request/response models (source of truth for API.md)
      dependencies.py   # shared FastAPI dependencies (e.g. get_data_provider)
    main.py           # FastAPI app assembly
  tests/
    unit/             # indicators, signals, risk — no I/O
    integration/      # API routers with mocked data providers
  pyproject.toml
```

`data/` adapters implement a common `DataProvider` protocol (`get_daily_ohlcv(ticker) -> DataFrame`, `get_weekly_ohlcv(ticker) -> DataFrame`, `get_extended_data(ticker) -> ExtendedData`) so `yfinance` and `stooq` are interchangeable and both are mockable in tests via the same fake.

`get_extended_data` (earnings/dividend dates, short interest, insider transactions -- docs/ideas.md; Elder ch. 37/53/58) is the one method that doesn't behave symmetrically across providers: `YFinanceProvider` implements it against `Ticker.calendar`/`Ticker.info`/`Ticker.insider_transactions`, all confirmed-live fields this app didn't previously expose, while `StooqProvider` has no equivalent data source at all (its plain CSV endpoint is OHLCV-only) and so never raises for this method -- it always returns an `ExtendedData` with every field null/empty and `unavailable_reason='fallback_provider_active'` set, an explicit "not supported by this provider" signal distinguishable from a real "checked, nothing found" null. `CachedDataProvider` caches this on a separate, longer TTL (3 days, vs. OHLCV's 24h) in its own `extended_data_cache` table (one row per ticker, not per date) -- this data changes far less often than a daily price bar. See the backend-market-data-extra-fields task's `decisions` entry for the full rationale.

## 3. Key Dependencies

| Package | Purpose |
|---|---|
| `fastapi` | API layer |
| `uvicorn` | ASGI server |
| `pandas` | OHLCV manipulation, resampling daily→weekly, and indicator calculations (hand-written against Analyse.md §4, not `pandas-ta` — see §1) |
| `yfinance` | Primary market data source |
| `sqlalchemy` + `alembic` | Persistence + migrations |
| `pydantic` | Request/response validation, settings |
| `pytest`, `pytest-cov`, `pytest-mock` | Testing (see [Testing.md](Testing.md)) |
| `httpx` | API integration tests (via FastAPI `TestClient`), and `IBKRProvider`'s real production HTTP client against the local IB Gateway (§8) |

## 4. Indicator Engine Notes

Each indicator is a pure function: `DataFrame in -> DataFrame/Series out`, no I/O, no global state. This is what makes 90% coverage realistic — indicator logic is the easiest code in the system to test exhaustively because it's deterministic math over fixed input.

Implement each indicator directly against its Analyse.md §4 definition and parameters (e.g., Force Index EMA periods, Stochastic %K/%D/smoothing) — there's no library default to fall back on, which removes the risk of a library's formula silently diverging from Elder's book definition.

## 5. Signal Engine

`signals/engine.py` is the orchestration point: pulls indicator outputs, evaluates Screen 1/2/3 (`triple_screen.py`), applies the Impulse gate (`impulse.py`), and produces `(signal, confidence, breakdown)` via `confidence.py`. The `breakdown` (per-component scores from Analyse.md §6) is returned to the API so the frontend can show *why* a confidence score is what it is, not just the number.

`analyse()`/`triple_screen.evaluate_tide`/`evaluate_wave`/`evaluate_trigger` are generic over whichever OHLCV data represents the currently active long-term/intermediate/short-term timeframe (`backend-day-trader-timeframe-mode-signal-engine`, §10 below) -- swing mode (this app's default/only mode in production) still feeds them weekly/daily data exactly as before, unchanged bar-for-bar. `analyse_day_trader()` is the day-trader-mode entry point: a thin wrapper over `analyse()` that also supplies `short_term_ohlcv`, so Screen 3 (Trigger) evaluates Elder's literal short-term-timeframe rule instead of swing mode's documented daily-bar approximation (docs/Analyse.md §2) -- the Impulse gate, Screen 2/Wave, and every indicator in `indicators` are unaffected, since they still read whichever frame plays the *intermediate* role, exactly as `evaluate_impulse`'s own "timeframe-agnostic" contract already documented before this task.

## 6. Portfolio & Risk Engine

`portfolio/risk.py` implements the 2%/6% rules and protective-stop calculation from Analyse.md §7, operating on `Position` + `Account` models. `portfolio/exits.py` evaluates the existing-position exit conditions independently of `signals/engine.py`'s fresh-entry logic — a held position can be flagged SELL purely on risk grounds even when the technical signal is HOLD.

`portfolio/pricing.py` holds the fetch-current-price-and-degrade-gracefully-per-ticker loop (`enrich_positions_with_price`/`EnrichedPosition`/`positions_value`) shared by `GET /api/portfolio` and `GET /api/portfolio/risk` (`api/routers/portfolio.py`): it turns each `PositionORM` row into a domain `Position` with `current_price`/`unrealized_pnl_pct` populated (both `None` on a failed fetch) alongside the `daily_ohlcv` frame the price was read from, so a caller that also needs recent history for the same ticker in the same request — `GET /api/portfolio/risk`'s protective-stop/exit-flag computation — can reuse it instead of re-fetching. It depends only on `data/base.py`'s `DataProvider` protocol, `data/exceptions.py`'s `DataProviderError` (caught in `_latest_close`'s per-ticker fetch), and `db/models.py`/`portfolio/models.py`, and is imported only from the `api/` layer.

## 7. Persistence

SQLite via SQLAlchemy for MVP: positions, account equity, a watchlist (ticker + added_at, keyed by ticker itself), closed trades (one row per closed position, realized P&L and exit details), a cache table for fetched OHLCV (ticker, date, OHLCV columns, fetched_at) to avoid re-hitting yfinance/Stooq on every request, a cache table for fetched extended data (fundamentals/sentiment, ticker + kind, fetched_at), a cache table for the fully-computed `GET /api/stocks/{ticker}/indicators` response itself (`indicator_history_cache`, keyed by `ticker` + `range`, same-calendar-day TTL rather than OHLCV's rolling 24h one -- `app.api.indicator_history_cache.IndicatorHistoryResponseCache`, docs/tasks/backend-indicator-history-performance.json), and a daily homework entries table (one row per calendar day, keyed by `date` itself, for ch. 57's "Am I ready to trade?" self-test -- see `app/portfolio/homework.py`). Migrations via Alembic (`app/db/migrations/`), wired to `app.db.models.Base.metadata` for autogenerate and to `app.config.get_settings().database_url` for the target database (see `app/db/migrations/env.py`) — see README.md's "Database migrations" section for the day-to-day workflow.

`app/main.py`'s FastAPI lifespan hook still calls `Base.metadata.create_all(bind=engine)` on startup — this is now just a convenience bootstrap (idempotent, a no-op against a database Alembic already migrated) so a brand-new dev/test SQLite file works immediately without running `alembic upgrade head` first, not a substitute for migrations going forward.

**Retrofitting Alembic onto a database created by the earlier `create_all`-only stopgap:** any database that predates this task (`db-migrations`) had its tables created by `create_all` directly, not by a migration — running `alembic upgrade head` against one fails (`CREATE TABLE` against a table that already exists). Run `alembic stamp head` instead, which records the initial migration as already applied without touching the schema (see `tests/integration/test_db_migrations.py` for both paths exercised as regression tests). This only works cleanly if that pre-existing schema actually matches what the initial migration would have created — e.g. a `positions` table created before `unique=True` was added to `PositionORM.ticker` (see the `api-portfolio-add-position` task's `decisions`) won't retroactively gain that index just because it gets stamped as head; a genuinely drifted database needs a manual fix-up, not a stamp. `scripts/fix_schema_drift.py` (see README.md's "Database migrations" section, and `docs/tasks/db-migrations-followups.json`) closes this one specific, currently-known drift case: it idempotently corrects `positions.ticker`'s index to unique if it's missing or wrong, no-ops if it's already correct, and fails loudly instead of silently succeeding if duplicate ticker rows already exist under the old non-unique index (a genuine data problem, not something to paper over). It is a narrow, targeted fix for this one case, not a general pre-stamp schema-diff tool — a future schema change that introduces a new kind of possible pre-Alembic drift needs its own fix, not an assumption that this script still covers it.

## 8. Optional: IBKR Client Portal Web API Provider

`app/data/ibkr_provider.py`'s `IBKRProvider` is an **optional, secondary** market-data
source (docs/tasks/backend-ibkr-data-provider.json, docs/ideas.md's "Decided: add IBKR's
Client Portal Web API" entry) used only for two capabilities the primary
yfinance/Stooq chain doesn't have: hourly bars (Screen 3 intraday entry-timing) and the
IBKR market scanner (broad-market-breadth detection). It deliberately does **not**
implement the `DataProvider` protocol (§2 above) — its capabilities don't map onto that
protocol's daily/weekly/extended-data shape — and nothing in the app currently consumes
it (`app.api.dependencies.get_ibkr_provider` is wired up but not yet called from any
route); it exists purely as infrastructure a future task can build an endpoint against.
See that module's own docstring, and this task's `decisions` entry, for the full
rationale.

**This is fully optional and off by default.** `Settings.ibkr_enabled` (env var
`FINTRADE_IBKR_ENABLED`) defaults to `False`, and every other part of the app —
including the full test/coverage suite — works identically whether or not it's set.
Turning it on requires a real, locally-running, authenticated IB Gateway; nothing here
is needed for normal development.

**Setup (only if you actually want to use this), matching the walkthrough captured
while scoping this task:**

1. Download `clientportal.gw.zip` from
   `download2.interactivebrokers.com/portal/clientportal.gw.zip` and unzip it.
2. Run `bin/run.sh root/conf.yaml` from that directory — this starts the gateway
   process, listening on `https://localhost:5000/` by default.
3. Open `https://localhost:5000/` in a browser and log in with your IBKR credentials.
   This step is genuinely interactive — IBKR does not support automating it — so it
   must be done by a human, once per session (the session expires after a period of
   inactivity and needs re-authenticating the same way).
4. Keep the session alive with a periodic `GET /tickle` call roughly once a minute
   while the gateway needs to stay authenticated. This is automated by the app itself
   (`docs/tasks/done/backend-ibkr-tickle-keepalive.json`): `app.main._ibkr_tickle_loop`
   runs as a FastAPI `lifespan` background task, started only when `Settings.ibkr_enabled`
   is `True`, calling `IBKRProvider.tickle()` every 45s and cleanly cancelled on app
   shutdown — nothing further to do here beyond the interactive login in step 3.
5. Set `FINTRADE_IBKR_ENABLED=true` (and `FINTRADE_IBKR_BASE_URL` if the gateway isn't
   at the default `https://localhost:5000/v1/api`) in the backend's environment.

**Endpoints used**, all under the gateway's `/v1/api` base:

- `GET /iserver/auth/status` — whether the gateway is running and the session is
  authenticated. `IBKRProvider.get_gateway_status()` wraps this into a typed
  `GatewayStatus` (`available` / `gateway_unreachable` / `not_authenticated`) rather
  than raising, so a caller can distinguish "gateway isn't running at all" from
  "running, but the browser login step hasn't been done (or has expired)" — checked
  before every other call this provider makes.
- `GET /iserver/marketdata/history` (`bar=1h` by default, or another of IBKR's
  documented `bar` values via `get_hourly_bars`'s `bar_size` parameter —
  `backend-ibkr-bar-interval-param`) — OHLCV bars, capped at 1,000 points per call
  (~41 days at `1h`) by IBKR itself; `get_hourly_bars` walks the `startTime` cursor
  backward across as many calls as needed to cover the requested lookback window, up to
  a fixed page-count safety bound.
- `GET /iserver/scanner/params` — the scanner's valid filter/instrument/location
  options, rate-limited by IBKR to 1 request/15 minutes; `get_scanner_params` caches
  the result for that same window rather than re-fetching on every call.
- `POST /iserver/scanner/run` — runs a scan (e.g. 52-week-high/low, hot-by-volume),
  rate-limited by IBKR to 1 request/second; `run_scanner` self-enforces that limit
  client-side (`IBKRRateLimitedError` if called again too soon) rather than always
  spending a real HTTP round-trip only to have the gateway reject it.
- `GET /iserver/secdef/search` (`?symbol=...`) — resolves a plain ticker symbol to
  IBKR's own numeric conid (docs/tasks/backend-ibkr-symbol-resolution.json), the id
  `get_hourly_bars`/`run_scanner` actually key off of. `resolve_conid` keeps only exact
  (case-insensitive) symbol matches that include a `"STK"` section (filtering out
  options/warrants/futures on the same underlying and fuzzy partial-symbol matches the
  endpoint can also return), and returns `None` -- never raises -- for both no match and
  a genuinely ambiguous one (more than one distinct conid for that symbol, e.g. dual
  listings on different exchanges) rather than guessing which contract was meant. See
  that task's `decisions` entry for the documented response shape this was implemented
  against.

**Known, accepted limitation — unverified against a live gateway.** Every one of the
above was implemented directly against IBKR's own documented Web API request/response
shapes (docs/ideas.md's own research), and every test in
`tests/unit/data/test_ibkr_provider.py` mocks HTTP at the `_request` boundary rather
than hitting a real gateway — no sandboxed/CI environment used to build or review this
has one. The actual response shapes returned by a live gateway, the interactive login
flow itself, and any undocumented quirks are therefore not verified end-to-end here;
this is deferred to manual testing by a user with a real running, authenticated
gateway. See this task's `decisions` entry.

## 9. CFTC Commitments of Traders (COT) Provider

`app/data/cftc_cot_provider.py`'s `CFTCCOTProvider` (docs/tasks/backend-cftc-cot-data.json,
docs/ideas.md's ch. 37 entry) is a small, standalone provider for Elder ch. 37's Commitments
of Traders framing — follow commercials, fade small speculators, read current positioning
against historical norms. Like `IBKRProvider` (§8), it deliberately does **not** implement
the `DataProvider` protocol (§2): its data is futures-market positioning for a fixed set of 5
major contracts, not per-stock-ticker OHLCV, and it's never wired into `app.signals`/
`app.portfolio` — it only backs `GET /api/cftc/cot` (docs/architecture/API.md), a genuinely
separate, informational surface.

Sourced from the CFTC's own public Socrata Open Data (SODA) JSON API
(`https://publicreporting.cftc.gov/resource/6dca-aqww.json`), confirmed live during this
task's research — the "Legacy"/"Futures Only" report, the classic Commercial/
Non-Commercial/Non-Reportable three-way breakdown Elder describes (the newer "Disaggregated"/
"Traders in Financial Futures" reports split those groups further, e.g. producer/merchant vs.
swap dealer, which this app doesn't need). No API key is required for this app's low request
volume. `COT_MARKETS` fixes the 5-market set (Euro, Yen, Oil, Gold, Bonds — matching the ch.
57 daily-homework idea's own list) to a specific `cftc_contract_market_code` per market,
confirmed against the live endpoint rather than assumed from the contract name alone (several
of these commodities have multiple CFTC-tracked contracts across different exchanges — e.g.
NYMEX WTI vs. ICE Brent for oil). See this task's `decisions` entry for the full research
writeup and the specific code chosen for each market.

`get_all_recent()` fetches every fixed market's trailing `WEEKS_OF_HISTORY` (52) weeks of
history in a single HTTP request (one compound `cftc_contract_market_code IN (...)` filter),
grouped client-side by market — not five separate per-market requests. `cot_index()` computes
the classic Williams "COT Index" (0-100, where the current net position sits within its own
trailing window's high/low range) as this provider's operationalization of "against
historical norms" — chosen over a bespoke percentile-rank scheme since it's the standard,
well-known form for exactly this data. No local caching/persistence layer (unlike
`CachedDataProvider`'s OHLCV/extended-data caches, §7): `GET /api/cftc/cot` fetches fresh on
every request, since the underlying data changes at most weekly and this is explicitly scoped
as a minimal, informational surface — see this task's `decisions` entry.

## 10. Day-Trader Timeframe Mode (foundational model + settings, in progress)

Elder ch. 39, "Choosing Timeframes -- the Factor of Five": Triple Screen doesn't hard-code
weekly/daily/intraday -- it's built around whatever three timeframes the trader picks, each
related to its neighbor by roughly a factor of five. `docs/tasks/
backend-day-trader-timeframe-mode.json` is landing this as a deliberately split, multi-PR
feature (see that task's own `decisions` entry for the full split rationale); this section
documents what exists **today**, not the full eventual feature.

**Landed so far:**

- `app.signals.timeframe` -- the generic domain model: `TimeframeUnit` (minute/day/week),
  `TimeframeInterval` (a count of a unit, with a canonical `"25m"`/`"1d"`/`"1w"`-style `code`),
  and `TimeframeTriple` (long-term/intermediate/short-term, replacing the app's hard-coded
  Tide/Wave/Trigger weekly/daily assumption for a future generic evaluation). Construction
  enforces one **hard** rule (`long_term > intermediate > short_term`, by trading-minute
  length) but only **warns** (`factor_of_five_warnings()`, never rejects) when a ratio falls
  outside a 2x-10x band -- ch. 39 itself frames "roughly a factor of five" as a guideline, and
  even the book's own 25-min/5-min/2-min day-trading example isn't a clean 5x on both legs
  (25/5 = 5x, but 5/2 = only 2.5x). See that module's own docstrings and this task's
  `decisions` entry for the full reasoning, including why `WEEK` is kept as its own unit
  (rather than collapsing everything to a minute count) to preserve the calendar-anchored
  weekly-resampling semantic `app.signals.engine._long_term_through_bar_date` (renamed from
  `_weekly_through_bar_date` by `backend-day-trader-timeframe-mode-signal-engine`, see below)
  already depends on.
- `app.trading_mode` + `TradingModeSettingORM` (`app/db/models.py`) -- global, app-wide
  settings persistence (a single settings row, same singleton-row convention as `AccountORM`
  §7 above) for the active `TradingMode` (`swing`/`day_trader`) and, once ever configured, the
  day-trader `TimeframeTriple`. A previously-configured day-trader triple is preserved (not
  cleared) across a switch back to `swing` mode, so a user toggling between modes doesn't lose
  their configuration -- see `TradingModeSettingORM`'s own docstring.
- `GET`/`PUT /api/settings/trading-mode` (`app.api.routers.settings`) -- reads/writes the
  setting above. `PUT` rejects (422) a `day_trader` mode request with no triple, or a triple
  violating the hard ordering rule; a factor-of-five-guideline violation is echoed back as a
  non-blocking `factor_of_five_warnings` list on the response instead.
- `app.data.day_trader_intraday` (`docs/tasks/backend-day-trader-timeframe-mode-ibkr-intraday.json`,
  extended by `backend-day-trader-timeframe-mode-signal-engine` to also fetch `long_term`) --
  fetches IBKR intraday bars for whichever `MINUTE`-unit leg(s) of the active day-trader triple
  need them, now uniformly across all three legs (`long_term`/`intermediate`/`short_term`) --
  not just `short_term`/`intermediate` as originally landed, since ch. 39's own fully-intraday
  day-trading examples (25-min/5-min/2-min, 39-min/8-min) need `long_term` fetched too, not just
  the common "long_term stays on a slower timeframe" case. A `DAY`/`WEEK`-unit leg still needs
  no IBKR call at all, since it's already served by the existing yfinance/Stooq daily/weekly
  pipeline. Reconciles IBKR's fixed, non-composable `bar` value set
  (`IBKRProvider._VALID_BAR_INTERVALS` -- §8 above) against the triple's fully-configurable
  minute counts by fetching the *largest IBKR-supported minute/hour bar size that evenly divides
  the requested interval* and resampling client-side into the exact requested width (same
  open/high/low/close/volume aggregation as `StooqProvider._resample_weekly`'s own
  daily-to-weekly precedent, generalized to an arbitrary minute count) -- e.g. a `"25m"` leg
  fetches IBKR's native `"5min"` bars and resamples 5:1, since `"25min"` isn't itself one of
  IBKR's valid `bar` values. Degrades every applicable leg to a typed, never-raised state
  (`available`/`disabled`/`gateway_unreachable`/`not_authenticated`/`unavailable`) exactly like
  every other IBKR-dependent feature in this app (§8's `GatewayStatus`,
  `app.api.routers.ibkr`'s existing pattern) -- `provider=None` (`Settings.ibkr_enabled=False`)
  means day-trader mode being *configured* never itself requires IBKR to be reachable. See that
  task's `decisions` entry for the full reconciliation writeup and the rejected alternative
  (restricting the triple's IBKR-backed legs to only IBKR-supported values).
- Generic Screen 1/2/3 (Tide/Wave/Trigger) evaluation
  (`backend-day-trader-timeframe-mode-signal-engine`) -- `app.signals.triple_screen
  .evaluate_tide`/`evaluate_wave`/`evaluate_trigger` already operated generically on whatever
  `pd.DataFrame` they're handed (no code path branches on "is this weekly/daily"), so the real
  work here was `app.signals.engine`'s orchestration layer: `analyse()` gained an optional
  `short_term_ohlcv` parameter (default `None`, reproducing the exact pre-existing behavior --
  Screen 3 evaluated on `daily_ohlcv` -- so swing mode, verified by regression tests asserting
  identical numeric output, is completely unaffected) that, when supplied, evaluates Screen 3
  against a genuinely distinct short-term-timeframe series instead of the daily-bar
  approximation. `analyse_day_trader()` is the day-trader-mode entry point: a thin wrapper
  supplying `long_term_ohlcv`/`intermediate_ohlcv`/`short_term_ohlcv` explicitly, still a pure
  domain function (no DB/IBKR dependency of its own -- resolving *which* frames to fetch for the
  active triple is left to `backend-day-trader-timeframe-mode-api`). The private
  `_weekly_through_bar_date` helper (`analyse_history`'s per-bar Tide truncation) was renamed to
  `_long_term_through_bar_date` and given a `long_term_unit` parameter (`WEEK`'s existing
  Friday-anchored logic unchanged/default; a new direct `<= bar_date` branch for `DAY`/`MINUTE`,
  covered by dedicated unit tests but not yet exercised by any real caller -- see below).
  Verified end to end with a mocked IBKR provider: `app.trading_mode` settings ->
  `app.data.day_trader_intraday` (all three legs) -> `analyse_day_trader` producing a real
  BUY/SELL/HOLD signal, confirming the Impulse gate/confidence scoring/Screen 1-2 remain
  timeframe-agnostic once Screen 3 is genericized (verify-elder-signal pass, this task's own
  `decisions` entry).

- `GET /api/stocks/{ticker}/analysis` and `GET /api/watchlist` (+ `GET /api/watchlist/breadth`,
  which shares the same underlying helper) (`backend-day-trader-timeframe-mode-api`) --
  `app.api.day_trader_signal.compute_day_trader_signal` resolves the active
  `app.trading_mode.get_trading_mode_setting` into fetched OHLCV frames (via
  `app.data.day_trader_intraday`, for a **fully-intraday triple only** -- see below) and calls
  `analyse_day_trader`, wired into both routers; swing mode's own behavior for every endpoint
  is unchanged (verified via the existing, unmodified regression test suite continuing to pass
  bar-for-bar). `AnalysisResponse.trading_mode`/`WatchlistResponse.trading_mode`
  (`TradingModeOut`) echo the active mode on both responses. **Field-naming decision** (this
  task's `decisions` entry): existing field names (`screens.tide.trend`,
  `weekly_macd_histogram_slope`, etc.) are deliberately NOT renamed to generic long-term/
  intermediate/short-term equivalents -- they're reinterpreted as "whichever timeframe
  currently fills that role" while day-trader mode is active, since a rename would be a
  breaking change to this app's only production frontend today for a still-incomplete feature
  (no settings UI yet). `GET /api/stocks/{ticker}/analysis` raises `503` (reusing its existing
  "market data provider unavailable" contract) rather than ever returning a partial/degraded
  body when day-trader data isn't available; `GET /api/watchlist` nulls the affected item's
  `signal`/`confidence`/`confidence_band` instead, matching its own pre-existing per-ticker
  degrade-gracefully convention.

- `app.signals.engine.analyse_history_day_trader` (`backend-day-trader-timeframe-mode-history`)
  -- the walk-forward, no-look-ahead historical replay `analyse_history()` already provides for
  swing mode's weekly/daily pair, generalized to a day-trader-mode `TimeframeTriple`'s
  long-term/intermediate/short-term legs -- for a future day-trader-mode chart overlay
  (`GET /api/stocks/{ticker}/indicators`'s own day-trader-mode wiring, still not yet landed --
  see the next bullet). A separate function from `analyse_history()`, not a generic parameter
  added to it, to keep swing mode's own already-reviewed implementation completely untouched.
  Truncates `long_term_ohlcv` via the existing `_long_term_through_bar_date` (its `MINUTE`
  branch, built ready for this by `backend-day-trader-timeframe-mode-signal-engine` but
  unexercised until now) and `short_term_ohlcv` via a new sibling helper,
  `_short_term_through_bar_date` -- both treat every leg's own bar timestamp as its "knowable
  as of" point uniformly (a deliberate, documented approximation given IBKR/this app's own
  client-side resampling both label a bar by its *start*, not its close -- see that function's
  own `decisions`-referenced docstring for the two more-precise alternatives considered and
  rejected). `app.data.day_trader_intraday.get_intraday_history_bars_for_triple` (plus its
  trading-mode-setting-driven counterpart, `get_active_day_trader_intraday_history_bars`) is
  the corresponding data-fetch shape this replay needs -- a much larger default `lookback_days`
  than the live-signal-snapshot `get_intraday_bars_for_triple`, clamped **per leg** to
  `app.data.ibkr_provider.max_lookback_days_for_bar_size`'s own bound for whichever IBKR-native
  granularity that leg resolves to (a new public helper on `IBKRProvider`'s module, computed
  from its existing `_MAX_PAGINATION_PAGES`/`_MAX_BARS_PER_PAGE`/`_BAR_INTERVAL_STEP`
  constants) -- no *new* IBKR-side pagination logic was needed, since `IBKRProvider
  .get_hourly_bars` already paginates arbitrarily deep (up to that same safety bound) for any
  `lookback_days` value; the clamp exists purely so a caller can know in advance how much
  history a given leg's granularity can actually return, rather than silently getting back
  less than asked for. Neither the new fetch functions nor `analyse_history_day_trader` are
  wired into any HTTP route yet -- that's the next bullet's job. See this task's `decisions`
  entry for the full writeup.

- `app.portfolio.risk.protective_stop`/`app.portfolio.profit_target.suggest_profit_target`/
  `app.portfolio.exits.evaluate_exit_flags`'s own hard-coded weekly/daily assumption
  (`backend-day-trader-timeframe-mode-portfolio-risk`) -- generalized the same way Screen 1-3
  were: none of these three functions ever actually special-cased "daily"/"weekly" internally
  (each just operates on whatever `pd.DataFrame`/bar-count window it's handed), so this was
  primarily a documentation-and-testing task confirming that genericity is real, plus two
  genuine methodology decisions (see this task's `decisions` entry for both, including the
  alternatives considered and rejected): the SafeZone stop's `_SWING_LOW_WINDOW_BARS` (renamed
  from `_SWING_LOW_WINDOW_DAYS`, value unchanged at 10) stays a fixed **bar** count rather than
  a wall-clock-duration-derived one, since a day trader's own holding period is itself
  intraday -- "10 bars of whichever timeframe is actually being traded on" (ch. 39 p.161: stops
  live on the intermediate timeframe's own chart in either mode) tracks that far better than a
  fixed multi-week wall-clock span; and `suggest_profit_target`'s weekly-chart channel
  candidate (renamed internal helper `_long_term_channel_bounds`) generalizes to read the
  active triple's `long_term` leg in day-trader mode rather than staying scoped to swing mode
  only, per ch. 39 p.161's own generic "long-term chart" framing -- `evaluate_exit_flags`'s
  `tide_flipped_bearish` flag (a direct `evaluate_tide` call) generalizes the identical way.
  Swing mode's own behavior is unchanged bar-for-bar (regression-tested), and new discriminating
  tests (including a mocked-IBKR integration test mirroring the signal-engine task's own)
  confirm the genericized functions actually read whichever intermediate/long-term-role data
  they're handed, intraday-shaped or not, rather than silently defaulting to swing-mode-only
  behavior. **Not yet wired into either real caller**: `GET /api/stocks/{ticker}/analysis`'s
  `profit_target` and `GET /api/portfolio/risk` (which calls all three of these functions) still
  always pass literal daily/weekly bars regardless of the active `TradingMode` -- that wiring is
  `backend-day-trader-timeframe-mode-api-followups`'s job (next bullet), same as before this
  task, since it also raises the separate per-position-day-trader-mode-fetch latency question
  that task's own scoping already deferred.

- `GET /api/stocks/{ticker}/indicators` and `GET /api/portfolio`/`GET /api/portfolio/risk`
  (`backend-day-trader-timeframe-mode-api-followups`) -- the two endpoints
  `backend-day-trader-timeframe-mode-api` deferred are now wired. `/indicators`'s day-trader-mode
  branch (`app.api.routers.stocks._get_day_trader_indicator_history`) fetches the active
  triple's three legs via `app.api.day_trader_signal.fetch_day_trader_history_legs` (a new
  sibling of `fetch_day_trader_legs`, wrapping `get_intraday_history_bars_for_triple`) and
  replays `analyse_history_day_trader` over the intermediate leg, checking the active trading
  mode *before* touching the swing `DataProvider` at all (unlike `/analysis`'s own day-trader
  branch, which still fetches daily/weekly first -- a deliberate difference for a route built
  fresh by this task, see its own `decisions` entry) -- and, unlike swing mode, never reads or
  writes the same-calendar-day `IndicatorHistoryResponseCache` (a whole-day TTL designed for
  once-daily-cadence data would be actively wrong, not just stale, for intraday bars). `range`'s
  existing `<N>d`/`<N>w`/`<N>m`/`<N>y`/`max` grammar still applies unchanged (no new minute/hour
  unit added -- a real, accepted limitation for a fine-grained intraday chart, see this task's
  `decisions` entry) and still only trims *returned* points, not what's fetched.
  `/portfolio`/`/portfolio/risk` now wire the genericized `app.portfolio.risk`/`profit_target`/
  `exits` layer (`backend-day-trader-timeframe-mode-portfolio-risk`) in: `/portfolio`'s
  per-position `signal`/`confidence`/`confidence_band` and `/portfolio/risk`'s per-position
  `protective_stop`/`trailing_stop`/`exit_flags`/`profit_target` both land in the same PR (the
  portfolio-risk task had already landed a genericized risk layer by the time this task started,
  removing the original inconsistent-partial-wiring concern that motivated deferring them
  separately) -- `current_price`/`unrealized_pnl_pct`/`equity`/the 6%-rule total stay
  swing-provider-derived either way, matching `/analysis`'s own `as_of`/`extended_data`/
  `profit_target` precedent. The per-position-latency concern is resolved via a new per-ticker
  concurrent fan-out (`app.api.day_trader_signal.compute_day_trader_signals_concurrently`/
  `fetch_day_trader_legs_concurrently`, a small bounded thread pool), also now used by
  `GET /api/watchlist`/`GET /api/watchlist/breadth` (closing a PR #313 review finding about
  their own previously fully-sequential per-ticker day-trader-mode loop). `PortfolioResponse`/
  `RiskResponse`/`IndicatorHistoryResponse` each gained a `trading_mode` field, mirroring
  `AnalysisResponse`/`WatchlistResponse`'s existing one. See this task's `decisions` entry for
  the full writeup, including a genuine bug this wiring surfaced and fixed:
  `app.portfolio.risk.ratchet_trailing_profit_stop` raised `TypeError` comparing a tz-aware
  `DatetimeIndex` (IBKR-sourced day-trader-mode OHLCV) against a naive `pd.Timestamp` --
  unreachable by any swing-mode caller (whose OHLCV index is always naive), so never caught by
  that function's own prior review passes.

**Not yet landed** (tracked as dependent follow-up tasks):

- A day-trader triple with any non-`MINUTE`-unit leg (a mixed triple, e.g. `long_term="1d"`) --
  `backend-day-trader-timeframe-mode-api`'s own `compute_day_trader_signal` only supports a
  **fully-intraday** triple (every leg `MINUTE`-unit, ch. 39's own canonical day-trading
  examples); a mixed triple degrades to the same "day-trader data unavailable" outcome as any
  other unavailable case, since `app.data.day_trader_intraday` has no fetch path for a
  `DAY`/`WEEK`-unit leg with an arbitrary (not literally daily/weekly) count, and building one
  is a distinct, unscoped data-fetching design problem.
- Frontend settings UI to view/switch the global trading mode and configure the day-trader
  timeframe triple (`frontend-day-trader-timeframe-mode-settings`) -- until this lands, every
  endpoint above is only reachable via `PUT /api/settings/trading-mode` directly (no UI control
  exists yet to switch into day-trader mode in the first place).

## Testing Notes

- Indicator unit tests assert against **hand-computed reference values** (small fixed input series, expected output computed independently, e.g. against a spreadsheet or a known textbook example) — not just "the function returns a Series of the right length."
- Data provider adapters are tested against **recorded fixtures** (a saved sample API response), never live network calls.
- Signal engine tests cover each Screen 1/2/3 + Impulse combination explicitly (bullish tide + green impulse + oversold wave + trigger fired → BUY with expected confidence range, etc.), not just the happy path.
- See [Testing.md](Testing.md) for the coverage gate and CI wiring.
