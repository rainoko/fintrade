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
    indicators/    # pure functions, one indicator per module
      ema.py
      macd.py
      force_index.py
      stochastic.py
      elder_ray.py
      autoenvelope.py
    signals/
      triple_screen.py   # Screen 1/2/3 evaluation
      impulse.py          # Impulse System gate
      confidence.py        # weighted scoring (Analyse.md §6)
      engine.py             # orchestrates the above into BUY/SELL/HOLD + %
    portfolio/
      models.py        # Position, Account (Pydantic/SQLAlchemy)
      risk.py           # 2% rule, 6% rule, protective stop calc
      exits.py           # existing-position exit rules (Analyse.md §7)
    db/
      models.py         # SQLAlchemy ORM models
      session.py
      migrations/        # Alembic
    api/
      routers/
        stocks.py
        portfolio.py
      schemas.py        # Pydantic request/response models (source of truth for API.md)
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

## 7. Persistence

SQLite via SQLAlchemy for MVP: positions, account equity, and a cache table for fetched OHLCV (ticker, date, OHLCV columns, fetched_at) to avoid re-hitting yfinance/Stooq on every request. Migrations via Alembic from day one, even though schema is simple — avoids a painful retrofit later.

## Testing Notes

- Indicator unit tests assert against **hand-computed reference values** (small fixed input series, expected output computed independently, e.g. against a spreadsheet or a known textbook example) — not just "the function returns a Series of the right length."
- Data provider adapters are tested against **recorded fixtures** (a saved sample API response), never live network calls.
- Signal engine tests cover each Screen 1/2/3 + Impulse combination explicitly (bullish tide + green impulse + oversold wave + trigger fired → BUY with expected confidence range, etc.), not just the happy path.
- See [Testing.md](Testing.md) for the coverage gate and CI wiring.
