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
      insider_clusters.py      # insider-transaction buy/sell classification + cluster detection (Elder ch. 37 p. 147)
    portfolio/
      models.py        # Position, Account (Pydantic/SQLAlchemy)
      pricing.py         # shared mark-to-market price enrichment (EnrichedPosition)
      risk.py           # 2% rule, 6% rule, protective stop calc
      exits.py           # existing-position exit rules (Analyse.md §7)
      profit_target.py    # suggested profit target + reward:risk ratio; signal-agnostic itself, gated BUY-only by one caller (fresh-signal analysis) but computed unconditionally by the other (an already-open position) (Analyse.md §7)
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

## Testing Notes

- Indicator unit tests assert against **hand-computed reference values** (small fixed input series, expected output computed independently, e.g. against a spreadsheet or a known textbook example) — not just "the function returns a Series of the right length."
- Data provider adapters are tested against **recorded fixtures** (a saved sample API response), never live network calls.
- Signal engine tests cover each Screen 1/2/3 + Impulse combination explicitly (bullish tide + green impulse + oversold wave + trigger fired → BUY with expected confidence range, etc.), not just the happy path.
- See [Testing.md](Testing.md) for the coverage gate and CI wiring.
