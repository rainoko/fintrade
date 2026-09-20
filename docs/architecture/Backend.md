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
      cache.py         # SQLite-backed OHLCV cache
      exceptions.py    # shared DataProviderError hierarchy (TickerNotFoundError, InsufficientHistoryError, DataProviderUnavailableError)
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
      swing_points.py        # shared fractal swing-high/swing-low detector (single series)
      support_resistance.py  # horizontal S/R zone detection + false-breakout flagging
      divergence.py           # MACD-H/Stochastic/RSI divergence detection (Analyse.md §4 row 11)
      kangaroo_tail.py         # Kangaroo Tail ("fingers") reversal-pattern detection (Analyse.md §4 row 13)
    portfolio/
      models.py        # Position, Account (Pydantic/SQLAlchemy)
      pricing.py         # shared mark-to-market price enrichment (EnrichedPosition)
      risk.py           # 2% rule, 6% rule, protective stop calc
      exits.py           # existing-position exit rules (Analyse.md §7)
      profit_target.py    # suggested profit target + reward:risk ratio for a fresh BUY (Analyse.md §7)
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

`data/` adapters implement a common `DataProvider` protocol (`get_daily_ohlcv(ticker) -> DataFrame`, `get_weekly_ohlcv(ticker) -> DataFrame`) so `yfinance` and `stooq` are interchangeable and both are mockable in tests via the same fake.

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
| `httpx` (via FastAPI `TestClient`) | API integration tests |

## 4. Indicator Engine Notes

Each indicator is a pure function: `DataFrame in -> DataFrame/Series out`, no I/O, no global state. This is what makes 90% coverage realistic — indicator logic is the easiest code in the system to test exhaustively because it's deterministic math over fixed input.

Implement each indicator directly against its Analyse.md §4 definition and parameters (e.g., Force Index EMA periods, Stochastic %K/%D/smoothing) — there's no library default to fall back on, which removes the risk of a library's formula silently diverging from Elder's book definition.

## 5. Signal Engine

`signals/engine.py` is the orchestration point: pulls indicator outputs, evaluates Screen 1/2/3 (`triple_screen.py`), applies the Impulse gate (`impulse.py`), and produces `(signal, confidence, breakdown)` via `confidence.py`. The `breakdown` (per-component scores from Analyse.md §6) is returned to the API so the frontend can show *why* a confidence score is what it is, not just the number.

## 6. Portfolio & Risk Engine

`portfolio/risk.py` implements the 2%/6% rules and protective-stop calculation from Analyse.md §7, operating on `Position` + `Account` models. `portfolio/exits.py` evaluates the existing-position exit conditions independently of `signals/engine.py`'s fresh-entry logic — a held position can be flagged SELL purely on risk grounds even when the technical signal is HOLD.

`portfolio/pricing.py` holds the fetch-current-price-and-degrade-gracefully-per-ticker loop (`enrich_positions_with_price`/`EnrichedPosition`/`positions_value`) shared by `GET /api/portfolio` and `GET /api/portfolio/risk` (`api/routers/portfolio.py`): it turns each `PositionORM` row into a domain `Position` with `current_price`/`unrealized_pnl_pct` populated (both `None` on a failed fetch) alongside the `daily_ohlcv` frame the price was read from, so a caller that also needs recent history for the same ticker in the same request — `GET /api/portfolio/risk`'s protective-stop/exit-flag computation — can reuse it instead of re-fetching. It depends only on `data/base.py`'s `DataProvider` protocol, `data/exceptions.py`'s `DataProviderError` (caught in `_latest_close`'s per-ticker fetch), and `db/models.py`/`portfolio/models.py`, and is imported only from the `api/` layer.

## 7. Persistence

SQLite via SQLAlchemy for MVP: positions, account equity, a watchlist (ticker + added_at, keyed by ticker itself), and a cache table for fetched OHLCV (ticker, date, OHLCV columns, fetched_at) to avoid re-hitting yfinance/Stooq on every request. Migrations via Alembic (`app/db/migrations/`), wired to `app.db.models.Base.metadata` for autogenerate and to `app.config.get_settings().database_url` for the target database (see `app/db/migrations/env.py`) — see README.md's "Database migrations" section for the day-to-day workflow.

`app/main.py`'s FastAPI lifespan hook still calls `Base.metadata.create_all(bind=engine)` on startup — this is now just a convenience bootstrap (idempotent, a no-op against a database Alembic already migrated) so a brand-new dev/test SQLite file works immediately without running `alembic upgrade head` first, not a substitute for migrations going forward.

**Retrofitting Alembic onto a database created by the earlier `create_all`-only stopgap:** any database that predates this task (`db-migrations`) had its tables created by `create_all` directly, not by a migration — running `alembic upgrade head` against one fails (`CREATE TABLE` against a table that already exists). Run `alembic stamp head` instead, which records the initial migration as already applied without touching the schema (see `tests/integration/test_db_migrations.py` for both paths exercised as regression tests). This only works cleanly if that pre-existing schema actually matches what the initial migration would have created — e.g. a `positions` table created before `unique=True` was added to `PositionORM.ticker` (see the `api-portfolio-add-position` task's `decisions`) won't retroactively gain that index just because it gets stamped as head; a genuinely drifted database needs a manual fix-up, not a stamp. `scripts/fix_schema_drift.py` (see README.md's "Database migrations" section, and `docs/tasks/db-migrations-followups.json`) closes this one specific, currently-known drift case: it idempotently corrects `positions.ticker`'s index to unique if it's missing or wrong, no-ops if it's already correct, and fails loudly instead of silently succeeding if duplicate ticker rows already exist under the old non-unique index (a genuine data problem, not something to paper over). It is a narrow, targeted fix for this one case, not a general pre-stamp schema-diff tool — a future schema change that introduces a new kind of possible pre-Alembic drift needs its own fix, not an assumption that this script still covers it.

## Testing Notes

- Indicator unit tests assert against **hand-computed reference values** (small fixed input series, expected output computed independently, e.g. against a spreadsheet or a known textbook example) — not just "the function returns a Series of the right length."
- Data provider adapters are tested against **recorded fixtures** (a saved sample API response), never live network calls.
- Signal engine tests cover each Screen 1/2/3 + Impulse combination explicitly (bullish tide + green impulse + oversold wave + trigger fired → BUY with expected confidence range, etc.), not just the happy path.
- See [Testing.md](Testing.md) for the coverage gate and CI wiring.
