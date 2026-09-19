from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, String
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
