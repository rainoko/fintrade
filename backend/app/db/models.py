from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PositionORM(Base):
    __tablename__ = "positions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    ticker: Mapped[str] = mapped_column(String, unique=True, index=True)
    quantity: Mapped[float] = mapped_column(Float)
    avg_cost_basis: Mapped[float] = mapped_column(Float)
    entry_date: Mapped[date] = mapped_column(Date)
    entry_notes: Mapped[str | None] = mapped_column(String, nullable=True)
    """Free-text "why did I take this trade" note (Elder ch. 59 Trade Journal Section A,
    docs/ideas.md's ch. 59 entry) -- optional, set at POST /api/portfolio/positions time.
    Carried over onto the corresponding `ClosedTradeORM.entry_notes` row when the position
    closes (`DELETE /api/portfolio/positions/{id}`) -- see the backend-trade-journal-entry-
    notes task's `decisions` entry for how a merge with an existing position (same ticker)
    combines an incoming note with an existing one rather than silently overwriting it."""
    strategy: Mapped[str | None] = mapped_column(String, nullable=True)
    """The trader's own personal, named strategy/setup tag for this trade (Elder ch. 55/56/
    58/59, docs/ideas.md's ch. 55/56 entry -- his own examples: "false breakout with a
    divergence," "pullback to value") -- optional free-text, set at POST
    /api/portfolio/positions time. Unlike `entry_notes` (a narrative note, appended on merge),
    an incoming `strategy` *overwrites* the existing one on a same-ticker merge rather than
    being concatenated onto it -- see the backend-trade-strategy-tagging task's `decisions`
    entry for why: this field is meant to be grouped/aggregated on exactly
    (docs/ideas.md's ch. 59 "equity curves segmented by strategy" idea, and the future
    backend-trade-apgar task), which a multi-value concatenated string would break. Carried
    over onto the corresponding `ClosedTradeORM.strategy` row when the position closes."""
    trailing_stop_high_water_mark: Mapped[float | None] = mapped_column(Float, nullable=True)
    """The highest `trailing_stop` (`app.portfolio.risk.ratchet_trailing_profit_stop`, Elder
    ch. 54 "Don't Let a Winning Trade Turn into a Loss") ever reported for this position,
    persisted here and used as a floor on every subsequent `GET /api/portfolio/risk` call --
    `None` until this position's profit has crossed the breakeven trigger for the first time.

    Added after this task's (backend-trailing-profit-stop) own original `decisions` entry
    explicitly rejected a persisted column in favor of a purely stateless recomputation from
    `position.avg_cost_basis` and full price history -- that stateless approach turned out to
    have the exact defect it was chosen to avoid: `POST /api/portfolio/positions`'s same-ticker
    merge can raise `avg_cost_basis` (a quantity-weighted average) with no price movement at
    all, which recomputes a HIGHER `entry_price`/`threshold_profit` on every subsequent call
    and can silently invalidate closes that used to qualify -- making the "reported" ratchet
    value decrease across a merge even though the stateless fold itself never revisits a given
    call incorrectly. A live PR review (see docs/tasks/backend-trailing-profit-stop.json's
    `review`/`decisions` for the reproduction and the revised rationale) caught this precise
    bug, which is what this column exists to close: the persisted high-water mark can only
    ever go up (`GET /api/portfolio/risk` writes `max(persisted, freshly_computed_candidate)`
    back on every call), so a subsequent `avg_cost_basis` change can lower the freshly
    *computed* candidate but never the *reported* value, which is always at least the floor.
    This does make `GET /api/portfolio/risk` the first side-effecting-write GET route in this
    codebase -- an accepted, narrow deviation now that the alternative (a value that can
    silently decrease, contradicting this field's own contract and docs/Analyse.md's "Move
    Your Stop Only in the Direction of Your Trade") has been shown to be unacceptable."""


class AccountORM(Base):
    """Single-row table holding the cash balance for this single-user MVP (docs/Architecture.md §4)."""

    __tablename__ = "account"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    cash: Mapped[float] = mapped_column(Float, default=0.0)


class WatchlistItemORM(Base):
    """A ticker the user is watching for a buy signal (docs/Analyse.md).

    Keyed by ticker itself rather than a synthetic id: a watchlist is a set of tickers
    (one entry per ticker, added/removed as a whole), unlike PositionORM where a synthetic
    id lets ticker stay a non-primary unique column for potential future multi-lot support.
    """

    __tablename__ = "watchlist_items"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime)


class ClosedTradeORM(Base):
    """A closed position -- one row per position closed via `DELETE
    /api/portfolio/positions/{id}` (app/api/routers/portfolio.py), recording enough to compute
    both halves of the book's actual 6% Rule (docs/Analyse.md §7, per docs/ideas.md's ch. 51
    cross-check: "the sum of your losses for the current month AND the risks in open trades" --
    see `app.portfolio.risk.realized_losses_pct`) and to feed the future backend-trade-grading
    task's buy/sell/trade-grade formulas plus a trade-journal frontend page -- see the
    backend-trade-history-table task's `decisions` entry for why these particular fields (and
    not, say, a running per-ticker lot ledger) were chosen.

    `exit_reason` is stored as a plain string (an `ExitReason` value, app/portfolio/models.py),
    the same "no DB-level enum constraint" convention `OHLCVCacheORM.interval` above already
    uses for its own closed string-enum-like column -- SQLite has no native enum type to
    enforce it at the DB layer regardless, so validation lives at the Python layer (the
    `ExitReason` enum itself) rather than being duplicated as a CHECK constraint here.

    `id` is a synthetic id (like `PositionORM.id`), not `ticker`, since a ticker can be closed
    and re-opened (and re-closed) many times over an account's lifetime -- each closure is its
    own row.
    """

    __tablename__ = "closed_trades"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    quantity: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    entry_date: Mapped[date] = mapped_column(Date)
    exit_price: Mapped[float] = mapped_column(Float)
    exit_date: Mapped[date] = mapped_column(Date, index=True)
    realized_pnl: Mapped[float] = mapped_column(Float)
    exit_reason: Mapped[str] = mapped_column(String)
    entry_notes: Mapped[str | None] = mapped_column(String, nullable=True)
    """Carried over verbatim from `PositionORM.entry_notes` (see its own docstring) at the
    moment the position closes -- null if the position never had a note recorded, matching
    `PositionORM.entry_notes`'s own optionality rather than inventing a placeholder string."""
    strategy: Mapped[str | None] = mapped_column(String, nullable=True)
    """Carried over verbatim from `PositionORM.strategy` (see its own docstring) at the moment
    the position closes -- null if the position never had a strategy tag recorded."""
    follow_up_notes: Mapped[str | None] = mapped_column(String, nullable=True)
    """Free-text note from the mandatory two-months-later follow-up review (Elder ch. 59
    Trade Journal Section E, docs/ideas.md's ch. 59 entry) -- reopening a closed trade with
    the benefit of hindsight and writing what it teaches. Set together with
    `follow_up_reviewed_at` by `POST /api/portfolio/closed-trades/{trade_id}/follow-up-review`;
    null until that review has actually happened. Unlike `entry_notes` (appended on a
    same-ticker position merge, since two buys can each have their own "why"), a follow-up
    review happens once per closed trade and is simply overwritten by a later call to the same
    endpoint -- see the backend-trade-journal-followup-review task's `decisions` entry."""
    follow_up_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    """UTC timestamp of the most recent follow-up review (naive UTC, matching every other
    timestamp column in this codebase -- see `app.time_utils`). Null means this trade hasn't
    been reviewed yet, which is exactly the condition `GET
    /api/portfolio/closed-trades?due_for_follow_up=true` filters on (together with the
    exit_date window) -- see that query parameter's own description for the window
    definition."""


class DailyHomeworkEntryORM(Base):
    """One row per calendar day of Elder's ch. 57 "Am I ready to trade?" 5-question
    psychological readiness self-test (docs/ideas.md's ch. 57 entry) -- purely subjective,
    no market data or provider calls involved. `date` is the primary key (not a synthetic
    id) since the whole point is exactly one entry per calendar day; a second `POST
    /api/daily-homework` for the same day overwrites that day's scores rather than creating
    a second row -- see the backend-daily-homework-self-test task's `decisions` entry.

    Each of the five scores is 0/1/2 per the book's own scale (validated at the Pydantic
    schema layer, `DailyHomeworkIn`/`DailyHomeworkOut` in app/api/schemas.py -- SQLite has no
    native CHECK-constraint enforcement wired up here, matching this codebase's existing
    "string-enum-like column, Python-layer validation only" convention for
    `ClosedTradeORM.exit_reason`/`OHLCVCacheORM.interval`). Their sum (0-10) and its
    book-defined red/yellow/green band are pure computations over these five columns
    (`app.portfolio.homework.band_for_total_score`) -- deliberately not stored themselves, so
    the derived value can never drift out of sync with a schema/threshold change the way a
    persisted copy could.
    """

    __tablename__ = "daily_homework_entries"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    physical_state_score: Mapped[int] = mapped_column(Integer)
    yesterday_trading_score: Mapped[int] = mapped_column(Integer)
    trade_planning_score: Mapped[int] = mapped_column(Integer)
    mood_score: Mapped[int] = mapped_column(Integer)
    schedule_score: Mapped[int] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(DateTime)


class OHLCVCacheORM(Base):
    """Cached market data, keyed by ticker + date + interval (docs/architecture/Backend.md §7)."""

    __tablename__ = "ohlcv_cache"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    interval: Mapped[str] = mapped_column(String, primary_key=True)  # 'daily' | 'weekly'
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)


class ExtendedDataCacheORM(Base):
    """Cached earnings/dividend dates, short interest, and insider transactions, keyed by
    ticker alone (a single current snapshot per ticker, unlike `OHLCVCacheORM`'s one row per
    date -- this data has no per-date history of its own the way OHLCV bars do; docs/
    architecture/Backend.md §7). `insider_transactions_json` stores
    `app.data.base.InsiderTransaction` rows as a JSON list (SQLite has no native array/JSON
    column type) rather than a separate child table -- this app only ever reads/writes the
    whole list at once per ticker, never queries into individual transactions, so a child
    table would add join complexity with no query benefit. `unavailable_reason` mirrors
    `app.data.base.ExtendedData.unavailable_reason` (currently only ever
    `'fallback_provider_active'`) -- see the backend-market-data-extra-fields task's
    `decisions` entry for why this whole result (not just OHLCV) is cached, and on a longer,
    separate TTL (`app.data.cache.CachedDataProvider`'s `_EXTENDED_DATA_CACHE_TTL`).
    """

    __tablename__ = "extended_data_cache"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    earnings_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    ex_dividend_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    shares_short: Mapped[int | None] = mapped_column(Integer, nullable=True)
    short_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    short_percent_of_float: Mapped[float | None] = mapped_column(Float, nullable=True)
    float_shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    insider_transactions_json: Mapped[str] = mapped_column(String)
    unavailable_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)


class IndicatorHistoryCacheORM(Base):
    """Cached `GET /api/stocks/{ticker}/indicators` response body, keyed by
    `(ticker, range)` (docs/tasks/backend-indicator-history-performance.json) --
    analogous to `OHLCVCacheORM`/`ExtendedDataCacheORM` above but one layer up the
    stack: those cache the raw provider data `app.data.cache.CachedDataProvider`
    fetches, while this caches the fully-computed `IndicatorHistoryResponse` itself
    (`app.api.indicator_history_cache.IndicatorHistoryResponseCache`), so a same-day
    repeat request for the same ticker/range skips the whole per-bar Triple Screen
    recompute in `app.signals.engine.analyse_history` -- not just the OHLCV fetch --
    entirely.

    `response_json` stores the response's own `model_dump_json()` (SQLite has no
    native JSON column type, same convention as `ExtendedDataCacheORM.
    insider_transactions_json`) rather than being decomposed into per-field columns:
    unlike `ExtendedDataCacheORM` (a fixed handful of scalar/list fields queried
    individually elsewhere), this whole row is only ever read back as one opaque
    `IndicatorHistoryResponse` blob (`IndicatorHistoryResponseCache.get`), never
    queried into by an individual field, so a decomposed schema would add no query
    benefit while coupling this table's shape to `IndicatorHistoryPoint`'s (which
    already changes independently as new indicators are added).

    `fetched_at` is compared against *calendar day*, not a rolling
    `timedelta`-based TTL like `OHLCVCacheORM`'s `_CACHE_TTL` -- see this task's
    `decisions` entry for why: the computed response is a pure function of
    "daily/weekly OHLCV as of today," so it's valid for the rest of the calendar day
    it was computed on regardless of what hour that was, and goes stale exactly at
    the UTC calendar-day boundary rather than N hours after the specific fetch time.
    """

    __tablename__ = "indicator_history_cache"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    range: Mapped[str] = mapped_column(String, primary_key=True)
    response_json: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)


class IBKRBreadthSnapshotORM(Base):
    """One row per (`series_key`, calendar day) IBKR-scanner-derived market-breadth count
    (docs/tasks/backend-market-breadth-indicators.json, Elder ch. 34-36's NH-NL/Advance-Decline
    breadth indicators). `series_key` is an opaque, caller-chosen label (e.g. `"nh"`/`"nl"` for
    the two sides of a New High-New Low reading, or `"adv"`/`"dec"` for Advance/Decline) --
    this app doesn't hardcode which IBKR scan-type code corresponds to which side, matching
    `backend-market-scanner`'s own established "don't guess unconfirmed category codes"
    precedent (see this task's `decisions` entry).

    `count` is `len(IBKRProvider.run_scanner(...))` for whatever `scan_config` the caller
    supplied the day this row was first recorded -- a single IBKR scan run is capped at a
    bounded, ranked shortlist of matching contracts (this module's own `ScannerResult`/
    `run_scanner` never expose a genuine full-market match count), so this is an explicitly
    bounded approximation, not a literal Elder NH-NL/Advance-Decline value -- see this task's
    `decisions` entry and docs/Analyse.md's "IBKR-scanner breadth approximation" section.

    Composite `(series_key, snapshot_date)` primary key (same style as `OHLCVCacheORM`'s
    `(ticker, date, interval)`) rather than a synthetic id: at most one recorded count per
    series per calendar day, so a second `POST /api/ibkr/breadth/snapshot` call for a
    `series_key` already recorded today is served from this existing row instead of running
    a second, redundant (and possibly rate-limited) scan.
    """

    __tablename__ = "ibkr_breadth_snapshots"

    series_key: Mapped[str] = mapped_column(String, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(DateTime)
